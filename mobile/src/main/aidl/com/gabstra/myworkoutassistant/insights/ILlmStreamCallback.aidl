package com.gabstra.myworkoutassistant.insights;

/** Streaming events for one send inside an :llm inference session. */
oneway interface ILlmStreamCallback {
    /** Decoded text so far (accumulated view of the current answer). */
    void onChunk(String text);

    /** The model answered with tool calls; JSON: [{"name":..., "arguments": {...}}]. */
    void onToolCalls(String toolCallsJson);

    /** The model produced a final answer. */
    void onCompleted(String text);

    /** The send failed; the session stays usable unless the process died. */
    void onError(String message);
}
