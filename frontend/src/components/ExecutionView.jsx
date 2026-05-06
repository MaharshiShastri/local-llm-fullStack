import React, { useState, useMemo, useEffect } from 'react';
import NeumorphicCard from './NeumorphicCard';
import { CheckCircle2, Circle} from 'lucide-react';
import { aiService } from '../services/api';

const ExecutionView = ({ plan, onComplete }) => {
  // --- STATE ---
  const [currentStep, setCurrentStep] = useState(0);
  const [timeLeft, setTimeLeft] = useState(0);
  const [totalStepTime, setTotalStepTime] = useState(0);
  const [isPaused, setIsPaused] = useState(false);
  const [isExecuting, setIsExecuting] = useState(false);
  const [isFinished, setIsFinished] = useState(false); 
  const [approvalData, setApprovalData] = useState(null);
  const [activeMissionId, setActiveMissionId] = useState(null);
  const [editableArtifact, setEditableArtifact] = useState("");
  const [localSteps, setLocalSteps] = useState([]);
  const [isResuming, setIsResuming] = useState(false);
const [lastUpdate, setLastUpdate] = useState(Date.now());
const WORKER_TIMEOUT = 5 * 60 * 1000; // 5 Minutes

  // Sync initial plan steps
  useEffect(() => { 
    const initialSteps = plan?.enriched_steps || plan?.steps || [];
    if(Array.isArray(initialSteps) && initialSteps.length > 0) {
      setLocalSteps(initialSteps);
    }
  }, [plan]);

  const allSteps = useMemo(() => localSteps, [localSteps]);
  const totalStepCount = allSteps.length || 1;

  useEffect(() => {
    if (plan?.mission_id || plan?.id) {
      setActiveMissionId(plan.mission_id || plan.id);
    }
  }, [plan]);

  // --- TIMER LOGIC ---
  useEffect(() => {
    let timer;
    if (isExecuting && !isPaused && timeLeft > 0) {
      timer = setInterval(() => {
        setTimeLeft(prev => Math.max(0, prev - 1));
      }, 1000);
    }
    return () => clearInterval(timer);
  }, [isExecuting, isPaused, timeLeft]);
  //Polling for celery task status
  const startExecution = async () => {
    try{
      await aiService.executeMission(missionId, (event) => {
        if (event.celery_task_id) {
                    setCeleryId(event.celery_task_id);
                }
            });
        } catch (err) {
            console.error("Execution failed to start", err);
        }
    };

    // The Polling Logic
    useEffect(() => {
    if (!celeryId || isPaused) return;

    const poll = async () => {
        try {
            const { data } = await aiService.getExecutionStatus(celeryId);
            
            // Check for worker timeout (Watchdog)
            if (Date.now() - lastUpdate > WORKER_TIMEOUT) {
                setStatus("LOST");
                stopPolling();
                return;
            }

            if (data.state !== status) {
                setLastUpdate(Date.now()); // Reset watchdog on any state change
                setStatus(data.state);
            }

            // If we were resuming and the status is now RUNNING, turn off the pulse
            if (isResuming && data.state === "RUNNING") {
                setIsResuming(false);
            }

            if (data.state === "WAITING_FOR_USER") {
                setApprovalData(data.details);
                setIsPaused(true);
                stopPolling();
            }
        } catch (err) {
            console.error("Polling error", err);
        }
    };

    const timer = setInterval(poll, 1500);
    return () => clearInterval(timer);
}, [celeryId, isPaused, lastUpdate]);

    const stopPolling = () => {
        if (pollTimer.current) clearInterval(pollTimer.current);
    };

    const handleResume = async () => {
        try {
            await aiService.approveStep(missionId, "completed", approvalData.step_id, userInput);
            setApprovalData(null);
            setUserInput("");
            // Re-start polling once the RESUME signal is sent to Redis
            setCeleryId(prev => `${prev}_resumed_${Date.now()}`); 
        } catch (err) {
            if (err.response?.status === 403) {
            setSecurityError(err.response.data.classify_failure);
        }
    }};
    useEffect(() => {
    // 1. On Mount: Check if there's a task left over in storage
    const savedTaskId = localStorage.getItem('active_mission_task');
    if (savedTaskId && !celeryId) {
        setCeleryId(savedTaskId);
    }
}, []);
const handleCancel = async () => {
    if (!celeryId) return;
    
    try {
        await aiService.cancelExecution(celeryId);
        stopPolling();
        localStorage.removeItem('active_mission_task');
        setCeleryId(null);
        setStatus("CANCELLED");
        setApprovalData(null);
    } catch (err) {
        console.error("Failed to kill task:", err);
    }
};
useEffect(() => {
    if (!celeryId) return;

    // 2. Persist the ID whenever it changes
    localStorage.setItem('active_mission_task', celeryId);

    const poll = async () => {
        try {
            const { data } = await aiService.getExecutionStatus(celeryId);
            setStatus(data.state);

            if (data.state === "WAITING_FOR_USER") {
                setApprovalData(data.details); 
                stopPolling(); 
            }

            // 3. Clear storage when the mission reaches a terminal state
            if (["SUCCESS", "FAILURE"].includes(data.state)) {
                localStorage.removeItem('active_mission_task');
                stopPolling();
            }
        } catch (err) {
            stopPolling();
        }
    };

    pollTimer.current = setInterval(poll, 1500);
    return () => stopPolling();
}, [celeryId]);
  // --- MISSION CONTROL ---
  const startMission = () => {
  if (!activeMissionId) return;
  setIsExecuting(true);
  setIsFinished(false);

  aiService.executeMission(activeMissionId, (payload) => {
  console.log("Received Event:", payload.event, payload); // Add this debug log
  
  switch (payload.event) {
    case "MANIFEST":
      if(payload.steps) setLocalSteps(payload.steps);
      break;

    case "STEP_STARTED":
      const idx = payload.index ?? 0;
      setCurrentStep(idx);
      const stepTime = payload.steps?.[idx]?.time_allocated || localSteps[idx]?.time_allocated || 60;
      setTimeLeft(stepTime);
      setTotalStepTime(stepTime);
      setIsPaused(false);
      break;
    case "REQUIRE_APPROVAL":
      setIsPaused(true);
      setApprovalData({
        step_id: payload.step_id || payload.backend_step_id,
        index: payload.index,
        artifact: payload.content?.artifact,
        estimated: localSteps[payload.index]?.time_allocated || 0,
        actual: payload.content?.time_needed || 0,
        drift: payload.content?.drift || 0
      });
      setEditableArtifact(payload.content?.artifact || "");
      break;
      
    case "MISSION_COMPLETED":
      setIsExecuting(false);
      setIsFinished(true);
      break;

    case "ERROR":
      console.error("Execution Error:", payload.detail);
      setIsExecuting(false);
      break;
  }
});
  }
  const handleApproval = async (decision) => {
    if (!activeMissionId || !approvalData?.step_id) return;
    setisResuming(true);
    try {
      let finalStatus;
      if (approvalData.type === "CLARIFICATION") {
        finalStatus = "started"; // This breaks the 'awaiting_clarification' loop
      } else {
        finalStatus = decision === 'approve' ? 'completed' : 'refined';
      }
      await aiService.approveStep(activeMissionId, status, approvalData.step_id, editableArtifact);
      setApprovalData(null);
      setIsPaused(false);
    } catch (err) {
      console.error("API_APPROVAL_FAILED:", err);
    }
  };

  const stepProgress = totalStepTime > 0 ? (timeLeft / totalStepTime) * 100 : 0;

  return (
    <div className="flex-1 flex flex-col p-6 overflow-hidden">
      <NeumorphicCard className="flex-1 flex flex-col overflow-hidden bg-[#0f172a]/50 border-slate-800">
        
        {/* HEADER */}
        <div className="p-6 border-b border-slate-800/60">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-4">
               <div className="relative flex items-center justify-center">
                  <svg className="w-16 h-16 transform -rotate-90">
                    <circle cx="32" cy="32" r="28" stroke="currentColor" strokeWidth="3" fill="transparent" className="text-slate-800" />
                    <circle cx="32" cy="32" r="28" stroke="currentColor" strokeWidth="3" fill="transparent" 
                      strokeDasharray={175.9} 
                      strokeDashoffset={175.9 - (175.9 * stepProgress) / 100} 
                      className="text-cyan-500 transition-all duration-1000 ease-linear" />
                  </svg>
                  <span className="absolute text-[10px] font-black font-mono text-white">{Math.round(timeLeft)}S</span>
               </div>
               <div>
                  <h2 className="text-[10px] font-black text-cyan-500 tracking-widest uppercase">
                    {isFinished ? "COMPLETED" : isPaused ? "PAUSED" : "ACTIVE"}
                  </h2>
                  <p className="text-xl font-black uppercase italic">
                    Step {currentStep + 1} <span className="text-slate-600">/ {totalStepCount}</span>
                  </p>
               </div>
            </div>
            <div className="flex gap-3">
                {/* KILL SWITCH - Only shows when active/paused */}
                {(isExecuting || isPaused) && !isFinished && (
                    <button 
                        onClick={handleCancel}
                        className="px-4 py-3 bg-red-500/10 border border-red-500/50 rounded-full text-red-500 font-black uppercase text-[10px] hover:bg-red-500 hover:text-white transition-all"
                    >
                        Terminate
                    </button>
                )}

                {!isExecuting && !isFinished && (
                    <button onClick={startMission} className="px-6 py-3 bg-cyan-500 rounded-full text-black font-black uppercase text-[10px] hover:bg-cyan-400 transition-colors">
                        Initiate_Protocol
                    </button>
                )}
            </div>
          </div>
        </div>

        {/* SCROLLABLE BODY */}
        <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-6 custom-scrollbar">
          {allSteps.map((s, idx) => {
            const isCompleted = idx < currentStep || isFinished;
            const isActive = idx === currentStep && !isFinished;
            return (
              <div key={idx} className={`p-5 rounded-2xl border transition-all duration-500 ${isActive ? 'bg-slate-800/60 border-cyan-500/50 scale-[1.02]' : 'border-transparent opacity-40'}`}>
                <div className="flex items-start gap-4">
                  <div className="mt-1">
                    {isCompleted ? <CheckCircle2 size={20} className="text-emerald-500" /> : <Circle size={20} className={isActive ? "text-cyan-500 animate-pulse" : "text-slate-700"} />}
                  </div>
                  <div className="flex-1">
                    <p className={`text-sm font-black uppercase tracking-tight ${isActive ? 'text-white' : 'text-slate-400'}`}>
                      {s.description || s.step || "Initializing..."}
                    </p>

                    {isActive && approvalData && (
                      <div className="mt-6 space-y-4 animate-in">
                        <div className="grid grid-cols-3 gap-3">
                           <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-700">
                             <span className="text-[8px] text-slate-500 uppercase block font-black">Estimated</span>
                             <span className="text-xs font-mono text-slate-300">{approvalData.estimated}s</span>
                           </div>
                           <div className="bg-cyan-500/10 p-3 rounded-xl border border-cyan-500/30">
                             <span className="text-[8px] text-cyan-500 uppercase block font-black">Used</span>
                             <span className="text-xs font-mono text-cyan-400">{approvalData.actual}s</span>
                           </div>
                           <div className="bg-slate-900/80 p-3 rounded-xl border border-slate-700">
                             <span className="text-[8px] text-amber-500 uppercase block font-black">Drift</span>
                             <span className="text-xs font-mono text-amber-500">+{approvalData.drift}s</span>
                           </div>
                        </div>
                        <div className="space-y-2">
                          <label className="text-[9px] text-slate-400 uppercase font-black tracking-widest">Edit Artifact Result:</label>
                          <textarea 
                            value={editableArtifact}
                            onChange={(e) => setEditableArtifact(e.target.value)}
                            className="w-full bg-black/60 border border-slate-700 rounded-xl p-4 text-xs text-slate-300 font-mono focus:border-cyan-500 outline-none min-h-[120px] resize-none transition-colors"
                          />
                        </div>

                        <div className="flex gap-3 pt-2">
                          <button onClick={() => handleApproval('refine')} className="flex-1 py-4 bg-slate-800 hover:bg-slate-700 text-white text-[10px] font-black rounded-xl uppercase tracking-widest transition-all">Refine</button>
                          <button onClick={() => handleApproval('approve')} className="flex-1 py-4 bg-emerald-500 hover:bg-emerald-400 text-black text-[10px] font-black rounded-xl uppercase tracking-widest transition-all">Approve</button>
                        </div> 
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          <div className="h-4" />
        </div>
      </NeumorphicCard>
    </div>
    );
  };

export default ExecutionView;