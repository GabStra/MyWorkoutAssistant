package com.gabstra.myworkoutassistant.shared.utils

import android.content.Context
import android.content.res.Resources
import com.gabstra.myworkoutassistant.shared.R
import java.math.RoundingMode
import java.text.NumberFormat
import java.util.Locale

/**
 * Renders a [PlateauReason] into localized prose. The numeric values are owned
 * by [PlateauReason] / [PlateauSessionReason]; this object supplies the
 * localized surrounding text and formats the numeric values for the active
 * locale.
 */
object PlateauReasonFormatter {

    fun format(context: Context, reason: PlateauReason): String =
        format(context.resources, reason)

    fun format(resources: Resources, reason: PlateauReason): String =
        render(reason, resources.activeLocale()) { resourceId, args ->
            resources.getString(resourceId, *args)
        }

    internal fun render(
        reason: PlateauReason,
        locale: Locale = Locale.getDefault(),
        stringProvider: (resourceId: Int, args: Array<Any?>) -> String
    ): String {
        val sessionLines = reason.sessions.joinToString(separator = "\n") { session ->
            stringProvider(
                R.string.plateau_reason_session_line,
                arrayOf<Any?>(
                    session.sessionNumber,
                    formatWeight(session.bestWeightKg, locale),
                    session.bestReps
                )
            )
        }

        return buildString {
            append(
                stringProvider(
                    R.string.plateau_reason_summary,
                    arrayOf<Any?>(reason.windowSessionCount)
                )
            )
            append("\n\n")
            append(stringProvider(R.string.plateau_reason_recent_sessions, arrayOf<Any?>()))
            append("\n")
            append(sessionLines)
            append("\n\n")
            append(stringProvider(R.string.plateau_reason_recommendation, arrayOf<Any?>()))
        }
    }

    /**
     * Whole kilograms drop the decimals, fractional kilograms keep up to two
     * decimals using the locale's decimal separator, and a zero load is
     * reported as bodyweight.
     */
    internal fun formatWeight(weightKg: Double, locale: Locale): String {
        if (weightKg == 0.0) {
            return bodyweightAbbreviation(locale)
        }

        val numberFormat = NumberFormat.getNumberInstance(locale).apply {
            isGroupingUsed = false
            minimumFractionDigits = 0
            maximumFractionDigits = 2
            roundingMode = RoundingMode.HALF_UP
        }
        return numberFormat.format(weightKg) + KILOGRAM_UNIT
    }

    private fun bodyweightAbbreviation(locale: Locale): String =
        when (locale.language.lowercase(Locale.ROOT)) {
            "it" -> "PC"
            else -> "BW"
        }

    private fun Resources.activeLocale(): Locale {
        val locales = configuration.locales
        return if (locales.size() > 0) locales[0] else Locale.getDefault()
    }

    private const val KILOGRAM_UNIT = "kg"
}
