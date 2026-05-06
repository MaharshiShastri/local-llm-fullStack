import axios from 'axios';
const API_URL = "http://127.0.0.1:8000"
const API = axios.create({
    baseURL : API_URL,
});

API.interceptors.request.use((config) => {
    const token = localStorage.getItem("token");
    if(token)  config.headers.Authorization = `Bearer ${token}`;
    return config;
});

const fetchStream = async(endpoint, body, onChunk, method="POST") => {
    const token = localStorage.getItem('token');
    const options = {
        method: method,
        headers:{
            "Authorization": `Bearer ${token}`,
        }
    }
    if(method!=="GET") {options.headers["Content-Type"] = "application/json";
        options.body = body ? JSON.stringify(body) : null;}
    else {options.body = null;}

    const response = await fetch(`${API_URL}${endpoint}`, options);
    if (response.status === 401) throw new Error("UNAUTHORIZED");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    
    while(true){
        const {done, value} = await reader.read();
        if(done) break;
    
        buffer += decoder.decode(value, {stream: true});
        const lines = buffer.split("\n");
        buffer = lines.pop();
    
        for(const line of lines){
            const trimmedLine = line.trim();
            if(trimmedLine.startsWith("data: ")){
                try{
                    const jsonString = trimmedLine.replace("data: ", "");
                    const data = JSON.parse(jsonString);
                    console.log(data);
                    onChunk(data);
                    if(data.conversation_id)    localStorage.setItem("current_conv_id", data.conversation_id);
                } catch(e) {
                    console.error("Error parsing SSE line:", e);
                }
            }
        }
    }
}
export const authService = {
    login: (email, password) => API.post("/login", {email, password}),
    signup: (email, password) => API.post("/signup", {email, password}),
};

API.interceptors.response.use(
    (response) => response,
    (error) => {
        if(error.response && error.response.status === 401){
            localStorage.clear();
            window.location.reload();
        }
        return Promise.reject(error);
        if (error.response?.status === 403) {
            const reason = error.response.data.classify_failure || "Security validation failed.";
            alert(`Action Blocked: ${reason}`); // Display the classify_failure message
        }
        return Promise.reject(error);
    }
);

export const dashBoard = {
    kpi: () => API.get('/system/stats')
};

export const aiService = {
    // Stream plans
    streamPlan: (task, time_budget, conversationid, mode,  onChunk) => {
        const id = conversationid ? parseInt(conversationid) : null;
        return fetchStream("/plan", { task, time_budget: parseInt(time_budget), mode: mode, conversation_id: id }, onChunk);
    },
    //Stream chat
    streamChat: (history, conversationid, onChunk) => {
        const id = conversationid ? parseInt(conversationid) : null;
        return fetchStream("/chat-stream", { message: history, conversation_id: id }, onChunk);
    },
    //Get chat history
    getChatHistory: (conversationid) => {
        const id = conversationid ? parseInt(conversationid) : null;
        return API.get(`/conversation/${id}`);
    },
    //Get conversations
    getConversations: () => API.get("/conversations"),
    //Delete conversation
    deleteConversation: (conversationID) => API.delete(`/conversation/${conversationID}`),
    //Rrename conversation
    renameConversation: (conversationID, newName) => API.patch(`/conversation/${conversationID}?title=${encodeURIComponent(newName)}`),
    //CRUD for tasks
    getTasks: () => API.get("/tasks"),
    deleteTask: (taskID) => API.delete(`/task/${taskID}`),
    updateTaskStatus: (taskID, status) => API.patch(`/task/${taskID}`, {status}),
    
    executeMission: (missionId, onEvent) => {
        //const id = conversationId ? parseInt(conversationId) : null;
        return fetchStream(`/execute/${missionId}`, null, onEvent, "GET");
    },
    approveStep: (missionId, status, stepId, content) => {
        return API.patch(`/execute/${missionId}/approve`, {
            step_id: stepId,
            status: status,
            refined_artifact: content
        });
    },
    getExecutionStatus: (taskId) => API.get(`/execute/status/${taskId}`),
    cancelExecution: (taskId) => {
        return API.post(`/execute/cancel/${taskId}`);
    },
    getMemories: () => API.get("/memories"),
    addMemory: (memoryData) => API.post("/memory", memoryData),
    deleteMemory: (memoryId) => API.delete(`/memory/${memoryId}`),
    updateMemory: (memoryID, updates) => API.patch(`/memory/${memoryID}`, updates),
    uploadDocument: async (file) => {
        const formData = new FormData();
        formData.append("file", file);

        return API.post("/upload-doc", formData, {
            headers: {
                'Content-Type' : 'multipart/form-data',
            },
    });
    },
};
