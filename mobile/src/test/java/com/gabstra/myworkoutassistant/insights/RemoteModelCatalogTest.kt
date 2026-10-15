package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Test

class RemoteModelCatalogTest {

    @Test
    fun parseModelIds_readsIdsFromDataArray() {
        val body = """
            {
              "object": "list",
              "data": [
                {"id": "gpt-4.1-mini", "object": "model", "owned_by": "openai"},
                {"id": "gpt-4o", "object": "model", "owned_by": "openai"}
              ]
            }
        """.trimIndent()
        assertEquals(listOf("gpt-4.1-mini", "gpt-4o"), RemoteModelCatalog.parseModelIds(body))
    }

    @Test
    fun parseModelIds_toleratesExtraFieldsBlankIdsAndDuplicates() {
        val body = """
            {
              "data": [
                {"id": "llama-3.1", "meta": {"n_ctx_train": 131072}, "unknown_field": [1, 2]},
                {"id": "", "object": "model"},
                {"id": "qwen2.5"},
                {"id": "llama-3.1"},
                {"object": "model"}
              ]
            }
        """.trimIndent()
        assertEquals(
            listOf("llama-3.1", "qwen2.5"),
            RemoteModelCatalog.parseModelIds(body),
        )
    }

    @Test
    fun parseModelIds_sortsCaseInsensitively() {
        val body = """{"data": [{"id": "Zephyr"}, {"id": "alpha"}, {"id": "Mistral"}]}"""
        assertEquals(
            listOf("alpha", "Mistral", "Zephyr"),
            RemoteModelCatalog.parseModelIds(body),
        )
    }

    @Test
    fun parseModelIds_missingDataArrayReturnsEmpty() {
        assertEquals(emptyList<String>(), RemoteModelCatalog.parseModelIds("""{"error": "none"}"""))
    }

    @Test
    fun modelsEndpointUrl_appendsV1OnlyWhenMissing() {
        assertEquals(
            "https://host.example.com/v1/models",
            RemoteModelCatalog.modelsEndpointUrl("https://host.example.com"),
        )
        assertEquals(
            "https://host.example.com/v1/models",
            RemoteModelCatalog.modelsEndpointUrl("https://host.example.com/v1/"),
        )
    }
}
