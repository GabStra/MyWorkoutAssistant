package com.gabstra.myworkoutassistant.insights

/**
 * Read-only validator for the session numeric contract: the model is required to quote the
 * app-computed FACT lines, and the dangerous residual errors are numbers that EXIST in the
 * evidence but are bound to the wrong meaning (avg/peak swap, wrong zone scope, transposed
 * target pair) — the exact-string allowlist passes those. This validator detects them so the
 * insight pipeline can drop the offending line and offer the model one rewrite chance.
 *
 * Checks are deliberately precision-oriented and limited to the classes with real or
 * structural failure evidence; a skipped check only leaves the existing redact/drop chain
 * in charge, while a false violation drops a true sentence.
 */
internal data class SessionNumericFacts(
    val averageBpm: Int?,
    val peakBpm: Int?,
    val nextTargetBpm: Int?,
    val nextTargetMinutes: Int?,
    val checkTargetBpm: Int?,
    val checkTargetMinutes: Int?,
    val wholeSessionZonePct: Int?,
    val workZonePct: Int?,
)

internal data class SessionNumericViolation(
    /** The model text that misquotes a fact, quoted back in the rewrite prompt. */
    val quotedText: String,
    /** Fact-based correction the rewrite must apply. */
    val correction: String,
)

internal fun parseSessionNumericFacts(markdown: String): SessionNumericFacts? {
    if (!markdown.contains("FACT Session duration:")) return null

    val averagePeak = AVERAGE_PEAK_FACT_REGEX.find(markdown)?.groupValues
    val nextTarget = NEXT_TARGET_FACT_REGEX.find(markdown)?.groupValues
    val checkTarget = CHECK_TARGET_FACT_REGEX.find(markdown)?.groupValues
    val wholeZone = WHOLE_ZONE_FACT_REGEX.find(markdown)?.groupValues
    val workZone = WORK_ZONE_FACT_REGEX.find(markdown)?.groupValues

    fun groupInt(groups: List<String>?, index: Int): Int? =
        groups?.getOrNull(index)?.toIntOrNull()

    return SessionNumericFacts(
        averageBpm = groupInt(averagePeak, 1),
        peakBpm = groupInt(averagePeak, 2),
        nextTargetBpm = groupInt(nextTarget, 1),
        nextTargetMinutes = groupInt(nextTarget, 2),
        checkTargetBpm = groupInt(checkTarget, 1),
        checkTargetMinutes = groupInt(checkTarget, 2),
        wholeSessionZonePct = groupInt(wholeZone, 1),
        workZonePct = groupInt(workZone, 1),
    )
}

internal fun validateSessionNumericContract(
    markdown: String,
    facts: SessionNumericFacts,
): List<SessionNumericViolation> {
    val violations = mutableListOf<SessionNumericViolation>()

    for (line in markdown.lines()) {
        // Scoped HR claims (warm-up/rest/work period) have their own legitimate values in the
        // evidence; only session-scope mentions are checked to keep the validator precise.
        val sessionScoped = !SESSION_SCOPE_QUALIFIER_REGEX.containsMatchIn(line)

        if (sessionScoped && facts.peakBpm != null && facts.averageBpm != null) {
            PEAK_MENTION_REGEX.findAll(line).forEach { match ->
                val value = match.groupValues[1].toIntOrNull() ?: return@forEach
                if (value == facts.averageBpm && value != facts.peakBpm) {
                    violations += SessionNumericViolation(
                        quotedText = match.value,
                        correction = "the recorded peak is ${facts.peakBpm} bpm (the average is ${facts.averageBpm} bpm)",
                    )
                }
            }
        }

        if (sessionScoped && facts.averageBpm != null && facts.peakBpm != null) {
            AVERAGE_MENTION_REGEX.findAll(line).forEach { match ->
                val value = match.groupValues[1].toIntOrNull() ?: return@forEach
                if (value == facts.peakBpm && value != facts.averageBpm) {
                    violations += SessionNumericViolation(
                        quotedText = match.value,
                        correction = "the session average is ${facts.averageBpm} bpm (the peak is ${facts.peakBpm} bpm)",
                    )
                }
            }
        }

        if (facts.nextTargetBpm != null && facts.nextTargetMinutes != null) {
            TARGET_PAIR_MENTION_REGEX.findAll(line).forEach { match ->
                val bpm = match.groupValues[1].toIntOrNull()
                val minutes = match.groupValues[2].toIntOrNull()
                val matchesNextTarget = bpm == facts.nextTargetBpm && minutes == facts.nextTargetMinutes
                val matchesCheckTarget = bpm == facts.checkTargetBpm && minutes == facts.checkTargetMinutes
                if (!matchesNextTarget && !matchesCheckTarget) {
                    violations += SessionNumericViolation(
                        quotedText = match.value,
                        correction = "the next-session target is average heart rate at or under " +
                            "${facts.nextTargetBpm} bpm for about ${facts.nextTargetMinutes} minutes",
                    )
                }
            }
        }

        facts.wholeSessionZonePct?.let { wholePct ->
            WHOLE_SESSION_ZONE_PCT_MENTION_REGEX.findAll(line).forEach { match ->
                val value = match.groupValues[1].toIntOrNull() ?: return@forEach
                if (value != wholePct) {
                    violations += SessionNumericViolation(
                        quotedText = match.value,
                        correction = "$wholePct% of HR samples stayed inside the zone across the whole session" +
                            (facts.workZonePct?.let { " (the $it% figure covers work periods only)" } ?: ""),
                    )
                }
            }
        }

        facts.workZonePct?.let { workPct ->
            WORK_ZONE_PCT_MENTION_REGEX.findAll(line).forEach { match ->
                val value = match.groupValues[1].toIntOrNull() ?: return@forEach
                if (value != workPct) {
                    violations += SessionNumericViolation(
                        quotedText = match.value,
                        correction = "$workPct% of work-period samples stayed inside the zone",
                    )
                }
            }
        }
    }

    return violations.take(MAX_NUMERIC_CONTRACT_DROPS)
}

internal const val MAX_NUMERIC_CONTRACT_DROPS = 4

// FACT-line parsers. The lines are generated by WorkoutSessionFactsBuilder with stable wording.
private val AVERAGE_PEAK_FACT_REGEX = Regex("""FACT Average heart rate: (\d{1,3}) bpm; peak (\d{1,3}) bpm""")
private val NEXT_TARGET_FACT_REGEX =
    Regex("""FACT Next-session target: average heart rate at or under (\d{1,3}) bpm for about (\d{1,3}) minutes""")
private val CHECK_TARGET_FACT_REGEX =
    Regex("""FACT Previous-session target check: the target was average HR at or under (\d{1,3}) bpm for about (\d{1,3}) minutes""")
private val WHOLE_ZONE_FACT_REGEX =
    Regex("""FACT Whole-session time in target zone: (\d{1,3})% of HR samples inside""")
private val WORK_ZONE_FACT_REGEX = Regex("""Work samples in target zone: (\d{1,3})%""")

// Output-mention patterns the validator checks against the facts.
private val PEAK_MENTION_REGEX =
    Regex("""\bpeak(?:ed)?(?:\s+heart\s+rate)?(?:\s+(?:of|at|was|reached|hit))?\s*(\d{1,3})\s*bpm""", RegexOption.IGNORE_CASE)
private val AVERAGE_MENTION_REGEX =
    Regex("""\baverag(?:e|ed)(?:\s+heart\s+rate)?[^.\n]{0,20}?(\d{1,3})\s*bpm""", RegexOption.IGNORE_CASE)
private val TARGET_PAIR_MENTION_REGEX =
    Regex("""at or under (\d{1,3}) bpm for about (\d{1,3}) minutes""", RegexOption.IGNORE_CASE)
private val WHOLE_SESSION_ZONE_PCT_MENTION_REGEX =
    Regex("""(\d{1,3})\s*%[^.\n]{0,60}?\b(?:whole|entire)\s+session[^.\n]{0,60}?zone""", RegexOption.IGNORE_CASE)
private val WORK_ZONE_PCT_MENTION_REGEX =
    Regex("""(\d{1,3})\s*%[^.\n]{0,60}?\b(?:work(?:\s+(?:period|samples))?|main set)[^.\n]{0,60}?zone""", RegexOption.IGNORE_CASE)

/**
 * Mentions inside these scopes carry their own legitimate numbers (work avg vs session avg,
 * rest peak vs session peak); checking them would need intent detection, so they are skipped.
 */
private val SESSION_SCOPE_QUALIFIER_REGEX = Regex(
    """warm[- ]?up|cool[- ]?down|rest|recover|work\s+(?:hr|period|samples)|main set|interval|previous|last session""",
    RegexOption.IGNORE_CASE,
)
