package com.gabstra.myworkoutassistant.insights;

import com.gabstra.myworkoutassistant.insights.ILlmStreamCallback;

/**
 * Gateway to the isolated :llm inference process. The gateway owns the LiteRT-LM
 * engine and one conversation per session; the main process drives tool rounds
 * and post-processing locally, so a native crash here can never take the app down.
 */
interface ILlmEngineGateway {
    /**
     * Creates a conversation-bound session. Blocks while the engine initializes.
     * spec keys (see LlmEngineIpcContract): model_path, cache_dir, backend_preference,
     * vision_enabled, system_prompt, max_output_token, initial_messages
     * (ArrayList<Bundle>{role, content}), tool_specs (ArrayList<String> JSON).
     */
    String createSession(in Bundle spec);

    /**
     * Sends one message into the session's conversation and streams the answer.
     * message keys: type ("user" | "image_text" | "tool_responses"), text,
     * image_path, tool_responses (ArrayList<Bundle>{name, response}).
     * Terminal callback events: onToolCalls, onCompleted, onError.
     */
    void sendMessage(String sessionId, in Bundle message, ILlmStreamCallback callback);

    void cancelSession(String sessionId);

    void closeSession(String sessionId);

    void trimIfIdle();
}
