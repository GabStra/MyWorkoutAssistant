package com.gabstra.myworkoutassistant.insights

internal data class InsightRepetitionResult(
    val reason: String,
    val repeatedText: String,
)

internal class InsightRepetitionDetector(
    private val minTotalCharacters: Int = 240,
    private val minRepeatedUnitCharacters: Int = 28,
    private val maxRepeatedUnitCharacters: Int = 240,
    private val minRepeatCount: Int = 3,
    private val tailCharactersToInspect: Int = 1_600,
) {
    fun detect(text: String): InsightRepetitionResult? {
        val normalized = normalizeForRepetitionDetection(text)
        if (normalized.length < minTotalCharacters) return null

        val tail = normalized.takeLast(tailCharactersToInspect)
        return detectRepeatedSuffix(tail)
    }

    private fun detectRepeatedSuffix(
        text: String,
    ): InsightRepetitionResult? {
        val maxUnitLength = minOf(maxRepeatedUnitCharacters, text.length / minRepeatCount)
        for (unitLength in minRepeatedUnitCharacters..maxUnitLength) {
            val repeatedText = text.takeLast(unitLength)
            if (!isMeaningfulRepeatedUnit(repeatedText)) continue

            val repeatCount = countTrailingRepeats(text, repeatedText)
            if (repeatCount >= minRepeatCount) {
                return InsightRepetitionResult(
                    reason = "suffix repeated $repeatCount times",
                    repeatedText = repeatedText
                )
            }
        }
        return null
    }

    private fun countTrailingRepeats(
        text: String,
        repeatedText: String,
    ): Int {
        var repeatCount = 0
        var endIndex = text.length
        while (endIndex >= repeatedText.length) {
            val startIndex = endIndex - repeatedText.length
            if (!text.regionMatches(
                    thisOffset = startIndex,
                    other = repeatedText,
                    otherOffset = 0,
                    length = repeatedText.length,
                    ignoreCase = false
                )
            ) {
                break
            }
            repeatCount += 1
            endIndex = startIndex
        }
        return repeatCount
    }

    private fun isMeaningfulRepeatedUnit(
        text: String,
    ): Boolean {
        val letterCount = text.count(Char::isLetter)
        if (letterCount < minRepeatedUnitCharacters / 2) return false

        val wordCount = Regex("""[a-z]+""")
            .findAll(text)
            .count()
        return wordCount >= 4
    }
}

private fun normalizeForRepetitionDetection(
    text: String,
): String {
    return text
        .lowercase()
        .replace(Regex("""\s+"""), " ")
        .replace(Regex("""\s+([,.;:!?])"""), "$1")
        .trim()
}
