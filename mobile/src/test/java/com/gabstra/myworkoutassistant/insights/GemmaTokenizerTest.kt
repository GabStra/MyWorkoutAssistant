package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/**
 * Golden tests against real SentencePieceProcessor over the exact asset bundled
 * with the app (Gemma tokenizer, model_type BPE). Regenerate expectations with:
 * SentencePieceProcessor(model_file=asset).encode(text).size
 */
class GemmaTokenizerTest {

    private val tokenizer: GemmaTokenizer by lazy {
        val candidates = listOf(
            File("src/main/assets/insights/gemma_tokenizer.model"),
            File("mobile/src/main/assets/insights/gemma_tokenizer.model"),
        )
        val modelFile = candidates.firstOrNull(File::exists)
            ?: error("gemma_tokenizer.model not found from ${File(".").absolutePath}")
        GemmaTokenizer.from(modelFile.readBytes())
    }

    private val goldenCases = listOf(
        "Hello, world!" to 4,
        "Barbell Back Squat: 3 sets x 8 reps @ 102.5 kg" to 21,
        "  leading and  double  spaces " to 8,
        "naïve café 你好" to 6,
        "3.14159" to 7,
        "user@example.com" to 5,
        "Average HR 142 bpm, peak 163 bpm, drift +7 bpm over 41 minutes." to 25,
        "## Session Overview\nZone distribution: Z1 5%, Z2 12%, Z3 41%, Z4 33%, Z5 9%." to 35,
        "tab\there new\nline" to 6,
        "multi   space run" to 4,
        "__init__ foo_bar 3x8@102.5" to 16,
        "Ελληνικά κείμενο 日本語テキスト 🎉🙂 ⚠️" to 13,
        "The quick brown fox jumps over the lazy dog. ".repeat(5).trimEnd() + " " to 51,
        "A" to 1,
        "" to 0,
        "na" to 1,
    )

    @Test
    fun countTokens_matchesSentencePiece() {
        for ((text, expected) in goldenCases) {
            assertEquals("token count mismatch for \"$text\"", expected, tokenizer.countTokens(text))
        }
    }

    @Test
    fun countTokens_isDeterministicAcrossCalls() {
        val text = "Barbell Back Squat 3x8 @ 102.5 kg, RPE 8, HR 142 bpm — zone Z3 41%"
        val first = tokenizer.countTokens(text)
        repeat(3) {
            assertEquals(first, tokenizer.countTokens(text))
        }
    }
}
