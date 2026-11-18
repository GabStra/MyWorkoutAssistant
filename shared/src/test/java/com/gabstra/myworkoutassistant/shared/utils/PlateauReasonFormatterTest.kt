package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.R
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Locale

class PlateauReasonFormatterTest {

    @Test
    fun rendersExactEnglishOutput() {
        val reason = PlateauReason(
            windowSessionCount = 3,
            sessions = listOf(
                PlateauSessionReason(sessionNumber = 1, bestWeightKg = 100.0, bestReps = 10),
                PlateauSessionReason(sessionNumber = 2, bestWeightKg = 0.0, bestReps = 8),
                PlateauSessionReason(sessionNumber = 3, bestWeightKg = 62.5, bestReps = 12)
            )
        )

        val expected = "No improvement detected in the last 3 sessions.\n\n" +
            "Recent sessions:\n" +
            "• Session 1: 100kg × 10 reps\n" +
            "• Session 2: BW × 8 reps\n" +
            "• Session 3: 62.5kg × 12 reps\n\n" +
            "To break the plateau, try increasing weight, reps, or total volume."

        assertEquals(expected, PlateauReasonFormatter.render(reason, Locale.US, englishStrings()))
    }

    @Test
    fun rendersBodyweightAndDecimalsForActiveLocale() {
        val reason = PlateauReason(
            windowSessionCount = 3,
            sessions = listOf(
                PlateauSessionReason(sessionNumber = 1, bestWeightKg = 0.0, bestReps = 8),
                PlateauSessionReason(sessionNumber = 2, bestWeightKg = 62.5, bestReps = 10),
                PlateauSessionReason(sessionNumber = 3, bestWeightKg = 62.04, bestReps = 12)
            )
        )

        val expected = "Nessun miglioramento rilevato nelle ultime 3 sessioni.\n\n" +
            "Sessioni recenti:\n" +
            "• Sessione 1: PC × 8 ripetizioni\n" +
            "• Sessione 2: 62,5kg × 10 ripetizioni\n" +
            "• Sessione 3: 62,04kg × 12 ripetizioni\n\n" +
            "Per superare lo stallo, prova ad aumentare il carico, le ripetizioni o il volume totale."

        assertEquals(expected, PlateauReasonFormatter.render(reason, Locale.ITALIAN, italianStrings()))
    }

    @Test
    fun formatsWeightValuesWithLocaleAwareDecimals() {
        assertEquals("BW", PlateauReasonFormatter.formatWeight(0.0, Locale.US))
        assertEquals("100kg", PlateauReasonFormatter.formatWeight(100.0, Locale.US))
        assertEquals("62.5kg", PlateauReasonFormatter.formatWeight(62.5, Locale.US))
        assertEquals("62.4kg", PlateauReasonFormatter.formatWeight(62.4, Locale.US))
        assertEquals("62.04kg", PlateauReasonFormatter.formatWeight(62.04, Locale.US))

        assertEquals("PC", PlateauReasonFormatter.formatWeight(0.0, Locale.ITALIAN))
        assertEquals("62,5kg", PlateauReasonFormatter.formatWeight(62.5, Locale.ITALIAN))
    }

    private fun englishStrings(): (Int, Array<Any?>) -> String {
        val strings = mapOf(
            R.string.plateau_reason_summary to
                "No improvement detected in the last %1\$d sessions.",
            R.string.plateau_reason_recent_sessions to "Recent sessions:",
            R.string.plateau_reason_session_line to "• Session %1\$d: %2\$s × %3\$d reps",
            R.string.plateau_reason_recommendation to
                "To break the plateau, try increasing weight, reps, or total volume."
        )
        return stringProvider(strings, Locale.US)
    }

    private fun italianStrings(): (Int, Array<Any?>) -> String {
        val strings = mapOf(
            R.string.plateau_reason_summary to
                "Nessun miglioramento rilevato nelle ultime %1\$d sessioni.",
            R.string.plateau_reason_recent_sessions to "Sessioni recenti:",
            R.string.plateau_reason_session_line to "• Sessione %1\$d: %2\$s × %3\$d ripetizioni",
            R.string.plateau_reason_recommendation to
                "Per superare lo stallo, prova ad aumentare il carico, le ripetizioni o il volume totale."
        )
        return stringProvider(strings, Locale.ITALIAN)
    }

    private fun stringProvider(
        strings: Map<Int, String>,
        locale: Locale
    ): (Int, Array<Any?>) -> String = { resourceId, args ->
        String.format(locale, strings.getValue(resourceId), *args)
    }
}
