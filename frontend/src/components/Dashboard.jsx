import React, { useEffect, useState } from 'react';
import { Activity, ShieldAlert, Target, Clock, Zap, AlertTriangle } from 'lucide-react';
import { dashBoard } from '../services/api';

const Dashboard = () => {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);

    const fetchStats = async () => {
        try {
            // Fix: ensure the variable name matches below
            const response = await dashBoard.kpi(); 
            if (response && response.data) {
                setStats(response.data);
                console.log(response.data);
            }
        } catch (error) {
            console.error("Failed to fetch telemetry:", error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStats();
        const interval = setInterval(fetchStats, 30000);
        return () => clearInterval(interval);
    }, []);

    if (loading) return (
        <div className="flex items-center justify-center min-h-screen bg-[#0f172a] text-white">
            <div className="animate-pulse font-mono uppercase tracking-widest">Initialising Telemetry...</div>
        </div>
    );

    return (
        <div className="p-8 bg-[#0f172a] min-h-screen text-slate-100 w-full overflow-y-auto">
            <header className="mb-10">
                <h1 className="text-4xl font-extrabold flex items-center gap-3 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
                    <Activity size={40} className="text-blue-400" /> SYSTEM_ROOT
                </h1>
                <p className="text-slate-400 mt-2 font-mono text-xs uppercase tracking-widest">Status: Monitoring Active</p>
            </header>

            {/* KPI Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
                <StatCard 
                    title="Reliability" 
                    value={`${stats?.reliability_score ?? 100}%`} 
                    icon={<ShieldAlert size={24}/>} 
                    color={stats?.reliability_score > 80 ? "border-emerald-500" : "border-red-500"} 
                />
                <StatCard 
                    title="Avg Latency" 
                    value={`${stats?.avg_latency_ms ?? 0}ms`} 
                    icon={<Clock size={24}/>} 
                    color="border-blue-500" 
                />
                <StatCard 
                    title="Grounding" 
                    value={`${stats?.grounding_accuracy ?? 0}%`} 
                    icon={<Target size={24}/>} 
                    color="border-purple-500" 
                />
                <StatCard 
                    title="Interventions" 
                    value={stats?.total_interventions ?? 0} 
                    icon={<Zap size={24}/>} 
                    color="border-yellow-500" 
                />
            </div>

            {/* Failure Distribution */}
            <div className="bg-slate-800/40 p-6 rounded-2xl border border-slate-700 shadow-xl">
                <h2 className="text-xl font-bold mb-6 flex items-center gap-2">
                    <AlertTriangle className="text-yellow-500" size={20} /> Failure Distribution
                </h2>
                
                <div className="space-y-6">
                    {stats?.failure_distribution && Object.keys(stats.failure_distribution).length > 0 ? (
                        Object.entries(stats.failure_distribution).map(([errorType, count]) => (
                            <div key={errorType} className="group">
                                <div className="flex justify-between text-sm mb-2">
                                    <span className="font-mono text-slate-300">{errorType}</span>
                                    <span className="font-bold">{count}</span>
                                </div>
                                <div className="w-full bg-slate-700 h-2 rounded-full overflow-hidden">
                                    <div 
                                        className="bg-blue-500 h-full transition-all duration-1000"
                                        style={{ width: `${Math.min(100, (count * 10))}%` }} 
                                    />
                                </div>
                            </div>
                        ))
                    ) : (
                        <div className="text-slate-500 italic text-center py-10">No critical failures logged.</div>
                    )}
                </div>
            </div>
        </div>
    );
};

// CRITICAL: This helper component must be defined!
const StatCard = ({ title, value, icon, color }) => (
    <div className={`bg-slate-800/60 p-6 rounded-2xl border-b-4 ${color} backdrop-blur-sm transition-transform hover:scale-[1.02]`}>
        <div className="flex justify-between items-center text-slate-400 mb-4">
            <span className="text-xs font-black tracking-widest uppercase">{title}</span>
            {icon}
        </div>
        <div className="text-4xl font-bold tracking-tight">{value}</div>
    </div>
);

export default Dashboard;