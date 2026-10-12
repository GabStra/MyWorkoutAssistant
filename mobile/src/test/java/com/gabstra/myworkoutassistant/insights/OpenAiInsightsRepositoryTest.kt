package com.gabstra.myworkoutassistant.insights

import com.openai.models.chat.completions.ChatCompletionChunk
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Test

class OpenAiInsightsRepositoryTest {

    @Test
    fun collectChatCompletionContent_keepsWhitespaceDeltasAndSkipsEmptyContent() = runBlocking {
        val chunks = listOf(
            contentChunk("## What"),
            contentChunk("\n\n"),
            contentChunk(""),
            contentChunk(" "),
            contentChunk(null),
            contentChunk("stood out\n"),
        )
        val collected = mutableListOf<String>()

        collectChatCompletionContent(chunks.iterator()) { collected.add(it) }

        assertEquals(listOf("## What", "\n\n", " ", "stood out\n"), collected)
    }

    @Test
    fun collectChatCompletionContent_ignoresUsageOnlyChunksWithoutChoices() = runBlocking {
        val chunks = listOf(
            ChatCompletionChunk.builder()
                .id("usage")
                .created(0L)
                .model("test-model")
                .choices(emptyList())
                .build(),
            contentChunk("done"),
        )
        val collected = mutableListOf<String>()

        collectChatCompletionContent(chunks.iterator()) { collected.add(it) }

        assertEquals(listOf("done"), collected)
    }

    private fun contentChunk(content: String?): ChatCompletionChunk {
        val delta = ChatCompletionChunk.Choice.Delta.builder()
        content?.let { delta.content(it) }
        return ChatCompletionChunk.builder()
            .id("chunk")
            .created(0L)
            .model("test-model")
            .addChoice(
                ChatCompletionChunk.Choice.builder()
                    .index(0L)
                    .delta(delta.build())
                    .build()
            )
            .build()
    }
}
