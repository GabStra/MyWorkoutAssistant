package com.gabstra.myworkoutassistant.insights

/**
 * Bundle keys shared by the :llm inference service and the main-process client.
 * Values cross AIDL as simple primitives so no custom parcelables are needed.
 */
internal object LlmEngineIpcContract {
    // createSession spec
    const val SPEC_MODEL_PATH = "model_path"
    const val SPEC_CACHE_DIR = "cache_dir"
    const val SPEC_BACKEND_PREFERENCE = "backend_preference"
    const val SPEC_VISION_ENABLED = "vision_enabled"
    const val SPEC_SYSTEM_PROMPT = "system_prompt"
    const val SPEC_MAX_OUTPUT_TOKEN = "max_output_token"
    const val SPEC_INITIAL_MESSAGES = "initial_messages" // ArrayList<Bundle>{ROLE, CONTENT}
    const val SPEC_TOOL_SPECS = "tool_specs" // ArrayList<String>: tool description JSON

    const val MESSAGE_ROLE = "role" // "user" | "model"
    const val MESSAGE_CONTENT = "content"

    // sendMessage message
    const val MESSAGE_TYPE = "type" // "user" | "image_text" | "tool_responses"
    const val MESSAGE_TEXT = "text"
    const val MESSAGE_IMAGE_PATH = "image_path"
    const val MESSAGE_TOOL_RESPONSES = "tool_responses" // ArrayList<Bundle>{NAME, RESPONSE}

    const val TOOL_RESPONSE_NAME = "name"
    const val TOOL_RESPONSE_PAYLOAD = "response"
}
