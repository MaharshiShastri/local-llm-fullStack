import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import NeumorphicCard from './NeumorphicCard';
import { ChevronLeft, Zap, Target, CheckCircle2, Circle} from 'lucide-react';
import { aiService } from '../services/api';

const PlanPanel = ({ onBack, input, setInput, onMetricsUpdate, activePlan, onCompleteExecution }) => {
  // --- UI & CONFIG STATE ---
  const [status, setStatus] = useState(activePlan ? 'executing' : 'idle'); // 'idle' | 'planning' | 'executing'
  const [timeBudget, setTimeBudget] = useState(600);
  const [planMode, setPlanMode] = useState('fast');
  const [liveMetrics, setLiveMetrics] = useState();
  const [currentStep, setCurrentStep] = useState(0);
  const [timeLeft, setTimeLeft] = useState(0);
  const [totalStepTime, setTotalStepTime] = useState(0);
  // --- EXECUTION DATA STATE ---
  const [activeMissionId, setActiveMissionId] = useState(null);
  const [steps, setSteps] = useState(activePlan?.steps || []);
  const [isPaused, setIsPaused] = useState(false);
  const [approvalData, setApprovalData] = useState(null);
  const [editableArtifact, setEditableArtifact] = useState("");
  const [showCompletion, setShowCompletion] = useState(false);
  const executionLock = useRef(null);
  
  // --- 1. THE PLANNING STREAM ---
  const startPlanning = async () => {
     if (!input.trim()) return;

    setStatus('planning');
    setSteps(Array(6).fill({ description: "ANALYZING_PHASE...", status: 'ghost' }));

    try {
      await aiService.streamPlan(input, timeBudget, null, planMode, (data) => {
        // Handle incremental steps appearing
        if (data.single_step) {
          setSteps(prev => {
          const newSteps = [...prev];
          const desc = data.single_step.step || data.single_step.description;
          // Replace the first 'ghost' found with real data
          const ghostIdx = newSteps.findIndex(s => s.status === 'ghost');
          if (ghostIdx !== -1) {
            newSteps[ghostIdx] = { ...data.single_step, description: desc, status: 'pending' };
          } else {
            newSteps.push({ ...data.single_step, description: desc, status: 'pending' });
          }
          return newSteps;
        });
         }

        // Handle final DB sync
        if (data.status === 'complete') {
          setActiveMissionId(data.mission_id);
          // Sync final enriched steps from DB
          const finalized = data.enriched_steps.map(s => ({
            id: s.backend_step_id,
            description: s.description,
            time_allocated: s.time_allocated,
            status: 'pending'
        }));

        setSteps(finalized); 
        setStatus('executing')
        }
      });
    } catch (err) {
      console.error("Planning Failed:", err);
      setSteps([]);
      setStatus('idle');
      alert("Mission Planning Failed: The AI remains silent.");
    }
  };

  // --- 2. THE EXECUTION ENGINE ---
  const initiateProtocol = useCallback((missionIdOverride=null) => {
    const targetId = missionIdOverride || activeMissionId

    if (!targetId || typeof targetId === 'object') {
        console.error("Protocol aborted: Invalid Mission ID", targetId);
        return;
    }
    
    if (missionIdOverride) {
        setActiveMissionId(missionIdOverride);
    }
    setIsPaused(false);
    console.log("Universal Protocol Initiated for Mission:", targetId);
    aiService.executeMission(targetId, (payload) => {
      let data = payload;
      if (typeof payload === 'string') {
        try {
          // Remove 'data: ' prefix if it exists and parse
          const clean = payload.replace(/^data:\s*/, '');
          data = JSON.parse(clean);
        } catch (e) {
          console.error("Failed to parse payload string", e);
          return;
        }
      }
      
      console.log("Processing Event:", data.event);
      switch (data.event) {
        case "MANIFEST":
          if (data.steps && data.steps.length > 0) {
            // This is the "Truth" from the DB. 
            // It will have all 6 steps, fixing the 1/1 issue instantly.
            setSteps(data.steps.map(s => ({
              id: s.backend_step_id || s.id,
              description: s.description,
              time_allocated: s.time_allocated,
              status: s.status
            })));
            }
            break;
        case "STRATEGIC_INTERRUPT":
          setIsPaused(true);
          setCurrentStep(data.index); // Sync UI to the interrupted step
          setApprovalData({
            step_id: data.step_id,
            index: data.index,
            type: "CLARIFICATION", // Distinguish from 'APPROVAL'
            reason: data.reason,
          });
          // Use the reason as the initial text to be edited/clarified
          setEditableArtifact(`[CLARIFICATION REQUESTED]: ${data.reason}\n\nMy response: `);
          break;
        
        case "STEP_STARTED":
          const idx = data.index ?? 0;
          console.log("MOVING_TO_STEP:", data.index);
          setCurrentStep(idx);
          setSteps(prev => prev.map((s, i) => 
          i === idx ?{
            ...s,
            tool_required: data.steps?.[idx]?.tool_required || s.tool_required,
            logic_reasoning: data.steps?.[idx]?.logic_reasoning || s.logic_reasoning

          } : s
        ));
          const duration = data.steps?.[idx]?.time_allocated || steps[idx]?.time_allocated || 60;
          setTimeLeft(duration);
          setTotalStepTime(duration);
          setIsPaused(false);
          setApprovalData(null);
          break;

        case "REQUIRE_APPROVAL":
          setIsPaused(true);
          setApprovalData({
            step_id: data.step_id || data.backend_step_id, 
            index: data.index,
            artifact: data.content?.description || "",
            estimated: steps[data.index]?.time_allocated || 0,
            actual: data.content?.time_needed || 0,
            drift: data.content?.drift || 0
          });
          setEditableArtifact(data.content?.description || "");
          break;

        case "STEP_COMPLETED":
          console.log(`Step ${data.index} verified.`);
          setSteps(prev => prev.map((s, i) => i === data.index ? { ...s, status: 'completed' } : s));
          setApprovalData(null);
          break;
        
          case "MISSION_COMPLETED":
          setStatus('idle');
          setActiveMissionId(null);
          setSteps([]);
          onMetricsUpdate(prev => ({ ...prev, status: 'STREAMS_READY', progress: 'DONE' }));
          break;
      
        case "TELEMETRY_PULSE":
          setLiveMetrics(data.metrics);
          onMetricsUpdate({
            latency: data.metrics.step_latency,
            interrupts: data.metrics.interrupt_count,
            progress: data.metrics.progress,
            status: "EXECUTING"
          });
          break;
      }
    });
  }, []);

  useEffect(() => {
    const planId = activePlan?.mission_id;
    if(planId && !executionLock.current !== planId){
      executionLock.current = planId;

      setSteps(activePlan.steps || []);
      setStatus('executing');

      const firstIncomplete = activePlan.steps.findIndex(
        s => s.status.toLowerCase() !== 'completed' && s.status !== 'STEP_COMPLETED'
      );
      setCurrentStep(firstIncomplete === -1 ? 0 : firstIncomplete);
      initiateProtocol(planId);
    }
    return () => {if (!activePlan?.mission_id) {executionLock.current = null;}}
  }, [activePlan?.mission_id, initiateProtocol]);
  // Timer Effect
  useEffect(() => {
    let timer;
    if (status === 'executing' && !isPaused && timeLeft > 0) {
      timer = setInterval(() => setTimeLeft(p => Math.max(0, p - 1)), 1000);
    }
    return () => clearInterval(timer);
  }, [status, isPaused, timeLeft]);

  const handleApproval = async (decision) => {
    if (!activeMissionId || !approvalData?.step_id) {
    console.error("Missing Mission ID or Step ID for approval");
    return;
  }
    const finalStatus = decision === 'approve' ? 'completed' : 'refined';
    try{
      await aiService.approveStep(activeMissionId, finalStatus, approvalData.step_id, editableArtifact);
      setApprovalData(null);
      setIsPaused(false);
    }catch(err){
      console.error("Approval failed:", err);
    }
  };
  const displayTotal = steps.length > 0 ? steps.length : 6;
  const progress = totalStepTime > 0 ? (timeLeft / totalStepTime) * 100 : 0;
   useEffect(() => {
    if(status === "finished"){
      setShowCompletion(true);
      const timer = setTimeout(() => setShowCompletion(false), 3000);
      return () => clearTimeout(timer);
    }
  }, [status]);
  // --- RENDER LOGIC ---
  return (
  <div className="flex-1 flex flex-col p-6 h-full overflow-hidden min-h-0 relative">
    {/* SHARED HEADER */}
    <div className="flex items-center justify-between mb-6 px-2 shrink-0">
      <button onClick={onBack} className="flex items-center gap-2 text-slate-500 hover:text-white transition group">
        <ChevronLeft size={16} className="group-hover:-translate-x-1 transition-transform" />
        <span className="text-[10px] font-black uppercase tracking-widest font-mono">Abort_Mission</span>
      </button>
      {status === 'executing' && (
        <div className="flex items-center gap-2 px-3 py-1 bg-slate-900/50 rounded-full border border-slate-800">
          <div className={`w-1.5 h-1.5 rounded-full ${isPaused ? 'bg-orange-500 animate-pulse' : 'bg-cyan-500 shadow-[0_0_8px_rgba(6,182,212,0.6)]'}`} />
          <span className="text-[9px] font-black text-slate-400 uppercase tracking-tighter">
            {isPaused ? 'Halt_Awaiting_Input' : 'Stream_Active'}
          </span>
        </div>
      )}
    </div>

    <NeumorphicCard className="flex-1 flex flex-col overflow-hidden min-h-0" inset>
      {/* STATE 1: IDLE (Mission Config) */}
      {status === 'idle' && (
        <div className="h-full w-full overflow-y-auto custom-scrollbar animate-in fade-in slide-in-from-bottom-4">
          <div className='p-12 max-w-2xl mx-auto space-y-10'>
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-orange-400">
                <Target size={24} className="animate-pulse" />
                <h1 className="text-3xl font-black tracking-tighter uppercase italic">Mission_Control</h1>
              </div>
              <p className="text-[10px] font-mono text-slate-500">READY_FOR_INITIALIZATION</p>
            </div>
            
            <div className="space-y-8 bg-slate-950/40 p-8 rounded-3xl border border-slate-800/50 shadow-2xl">
              <div className="space-y-2">
                <label className="text-[10px] font-bold text-slate-500 uppercase ml-2">Objective_Parameters</label>
                <textarea 
                  value={input} 
                  onChange={(e) => setInput(e.target.value)}
                  placeholder='Input your task/mission here....' 
                  className="w-full bg-slate-950 border border-slate-800 focus:border-cyan-500/50 rounded-2xl p-4 text-sm text-slate-200 outline-none min-h-[120px] resize-none transition-all font-mono shadow-inner"
                />
              </div>

              <div className="grid grid-cols-2 gap-8">
                <div className="space-y-4">
                  <div className="flex justify-between">
                    <label className="text-[10px] font-bold text-slate-500 uppercase">Budget</label>
                    <span className="text-[10px] font-mono text-cyan-500">{timeBudget}S</span>
                  </div>
                  <input type="range" min="60" max="3600" step="60" value={timeBudget} onChange={(e) => setTimeBudget(e.target.value)} className="w-full h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-500" />
                </div>

                <div className="space-y-4">
                  <label className="text-[10px] font-bold text-slate-500 uppercase">Heuristics</label>
                  <div className="flex gap-2 p-1 bg-black/40 rounded-xl border border-slate-800">
                    {['fast', 'deep'].map(m => (
                      <button key={m} onClick={() => setPlanMode(m)} className={`flex-1 py-2 rounded-lg text-[9px] font-black uppercase transition-all ${planMode === m ? 'bg-cyan-500 text-black' : 'text-slate-500 hover:text-slate-300'}`}>{m}</button>
                    ))}
                  </div>
                </div>
              </div>

              <button onClick={startPlanning} className="group relative w-full py-4 border-2 border-cyan-500/50 hover:border-cyan-500 rounded-2xl font-black text-xs uppercase tracking-widest transition-all overflow-hidden">
                <div className="absolute inset-0 bg-cyan-500 translate-y-full group-hover:translate-y-0 transition-transform duration-300" />
                <span className="relative group-hover:text-black">Initialize_Strategy_Stream</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* STATE 2: PLANNING */}
      {status === 'planning' && (
        <div className="flex-1 flex flex-col items-center justify-center p-12 min-h-0 animate-in fade-in">
          <Zap size={48} className="text-yellow-500 animate-pulse mb-6" />
          <p className="text-[10px] font-mono text-slate-500 tracking-[0.4em] mb-12">SYNTHESIZING_MANIFEST...</p>
          <div className="w-full max-w-md space-y-3 overflow-y-auto max-h-[40vh] custom-scrollbar pr-4">
            {steps.map((s, i) => (
              <div key={i} className="text-[11px] font-mono text-slate-400 p-2 border-l-2 border-slate-800 bg-slate-900/20">
                <span className="text-cyan-500 mr-2">[{i + 1}]</span> {s.description}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* STATE 3: EXECUTING */}
      {/* STATE 3: EXECUTING */}
{status === 'executing' && (
  <div className="flex-1 flex flex-col min-h-0 overflow-hidden h-full animate-in slide-in-from-right-4 duration-500">
    <div className="p-6 border-b border-slate-800/60 flex justify-between items-center bg-slate-900/40 shrink-0">
      <div className="flex items-center gap-5">
        <div className="relative w-14 h-14">
          <svg className="w-full h-full -rotate-90">
            <circle cx="28" cy="28" r="24" stroke="currentColor" strokeWidth="3" fill="transparent" className="text-slate-800" />
            <circle cx="28" cy="28" r="24" stroke="currentColor" strokeWidth="3" fill="transparent" strokeDasharray="150.8" strokeDashoffset={150.8 - (150.8 * progress) / 100} className={`${isPaused ? 'text-orange-500' : 'text-cyan-500'} transition-all duration-1000 shadow-[0_0_10px_rgba(6,182,212,0.5)]`} />
          </svg>
          <span className="absolute inset-0 flex items-center justify-center text-[10px] font-black font-mono">{timeLeft}S</span>
        </div>
        <div>
          <h2 className={`text-[9px] font-black uppercase tracking-[0.2em] ${isPaused ? 'text-orange-500' : 'text-cyan-500'}`}>
            {isPaused ? 'Protocol_Interrupt' : 'Neural_Execution'}
          </h2>
          <p className="text-xl font-black uppercase italic tracking-tighter">
            Phase {currentStep + 1} <span className="text-slate-700">/ {displayTotal}</span>
          </p>
        </div>
      </div>
      {timeLeft === 0 && !isPaused && (
        <button onClick={() => initiateProtocol(activeMissionId || activePlan?.mission_id)} className="px-8 py-3 bg-cyan-500 text-black text-[10px] font-black uppercase rounded-xl hover:scale-105 transition-transform shadow-[0_0_20px_rgba(6,182,212,0.3)]">
          {isPaused ? 'Resume_Agent' : 'Launch_Agent'}
        </button>
      )}
    </div>

    <div className="flex-1 overflow-y-auto p-6 space-y-4 custom-scrollbar min-h-0">
      {steps.map((s, idx) => {
        const isComp = idx < currentStep || s.status === 'completed';
        const isAct = idx === currentStep;
        const isClarification = isAct && approvalData?.type === "CLARIFICATION";

        return (
          <div key={idx} className={`p-5 rounded-2xl border transition-all duration-700 ${
            isAct 
              ? isClarification 
                ? 'bg-orange-500/5 border-orange-500/40 shadow-[0_0_30_px_rgba(249,115,22,0.05)]' 
                : 'bg-slate-800/40 border-cyan-500/40 shadow-[0_0_30px_rgba(56,189,248,0.1)]' 
              : 'border-slate-800/50 opacity-30 grayscale'
          }`}>
            <div className="flex gap-4">
              <div className="pt-1">
                {isComp ? <CheckCircle2 size={20} className="text-emerald-500" /> : <Circle size={20} className={isAct ? (isClarification ? "text-orange-500 animate-pulse" : "text-cyan-500 animate-pulse") : "text-slate-800"} />}
              </div>
              <div className="flex-1">
                {/* STEP DESCRIPTION */}
                <p className={`text-xs font-black uppercase tracking-tight mb-3 ${isAct ? 'text-slate-100' : 'text-slate-500'}`}>
                  {s.description}
                </p>

                {/* TOOLS & REASONING (Only visible for active/completed steps for clarity) */}
                {(isAct || isComp) && (
                  <div className="mb-4 space-y-2 animate-in fade-in duration-500">
                    <div className="flex items-center gap-2">
                      <span className="text-[8px] font-bold text-slate-500 uppercase tracking-widest">Tool required:</span>
                      <span className="text-[9px] font-mono font-black text-cyan-400 bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/20">
                        {s.tool_required || 'standard_compute'}
                      </span>
                    </div>
                    
                    {s.logic_reasoning && (
                      <div className="space-y-1">
                        <span className="text-[8px] font-bold text-slate-500 uppercase tracking-widest">Reason:</span>
                        <p className="text-[10px] text-slate-400 font-mono leading-relaxed italic bg-black/20 p-2 rounded-lg border border-slate-800/50">
                          {s.logic_reasoning}
                        </p>
                      </div>
                    )}
                  </div>
                )}
                
                {/* INTERACTION AREA (APPROVALS / CLARIFICATIONS) */}
                {isAct && approvalData && (
                  <div className="mt-5 space-y-4 animate-in fade-in slide-in-from-top-2 duration-400">
                    <div className="flex items-center gap-2">
                       <span className={`text-[9px] font-black px-2 py-0.5 rounded tracking-tighter ${isClarification ? 'bg-orange-500 text-black' : 'bg-cyan-500 text-black'}`}>
                         {isClarification ? 'ACTION_REQUIRED: AMBIGUITY_DETECTED' : 'ARTIFACT_VERIFICATION'}
                       </span>
                    </div>

                    {approvalData.reason && (
                      <div className="p-3 bg-orange-500/10 border-l-2 border-orange-500 rounded-r-lg">
                        <p className="text-[10px] text-orange-400 font-mono italic leading-relaxed">
                          &gt; {approvalData.reason}
                        </p>
                      </div>
                    )}

                    <textarea 
                      value={editableArtifact} 
                      onChange={(e) => setEditableArtifact(e.target.value)} 
                      className={`w-full bg-black/60 border rounded-xl p-4 text-[11px] font-mono min-h-[140px] text-slate-200 outline-none transition-all custom-scrollbar ${
                        isClarification ? 'border-orange-500/30 focus:border-orange-500' : 'border-slate-700 focus:border-cyan-500'
                      }`} 
                    />
                    
                    <div className="flex gap-3">
                      {!isClarification && (
                        <button onClick={() => handleApproval('refine')} className="flex-1 py-3 bg-slate-800 hover:bg-slate-700 text-[10px] font-black uppercase rounded-xl transition-colors text-slate-300">Refine</button>
                      )}
                      <button 
                        onClick={() => handleApproval('approve')} 
                        className={`flex-[2] py-3 text-black text-[10px] font-black uppercase rounded-xl transition-all shadow-lg ${
                          isClarification ? 'bg-orange-500 hover:bg-orange-400' : 'bg-emerald-500 hover:bg-emerald-400'
                        }`}
                      >
                        {isClarification ? 'Confirm_Clarification' : 'Approve_and_Proceed'}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
      <div className="h-20 shrink-0 w-full" />
    </div>
  </div>
)}
    </NeumorphicCard>

    {/* COMPLETION TOAST */}
    {showCompletion && (
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 w-full max-w-md bg-slate-900 border border-emerald-500/50 rounded-2xl p-5 shadow-[0_20px_50px_rgba(0,0,0,0.5)] animate-in slide-in-from-bottom-10 duration-500 z-[100]">
        <div className="flex justify-between items-start mb-4">
          <div className="flex gap-3">
            <div className="p-2 bg-emerald-500/20 rounded-lg">
              <CheckCircle2 className="text-emerald-500" size={20} />
            </div>
            <div>
              <p className="text-[10px] font-black uppercase text-emerald-400 tracking-widest mb-1">Mission_Successful</p>
              <p className="text-[11px] text-slate-400 font-mono leading-tight">Objective reached in {liveMetrics?.execution_time || timeBudget}s.</p>
            </div>
          </div>
        </div>
        <div className='h-1 w-full bg-slate-800 rounded-full overflow-hidden'>
          <div className="h-full bg-emerald-500" style={{ animation: "shrink 3s linear forwards" }} />
        </div>
      </div>
    )}
  </div>
);
};
export default PlanPanel;