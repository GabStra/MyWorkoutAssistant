package com.gabstra.myworkoutassistant.insights

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutNumericContractValidatorTest {

    private val factsMarkdown = """
        FACT Session duration: 55:09 (55 minutes)
        FACT Average heart rate: 140 bpm; peak 154 bpm
        FACT Whole-session time in target zone: 80% of HR samples inside 60-70% of heart-rate reserve (135-150 bpm)
        FACT Previous-session target check: the target was average HR at or under 131 bpm for about 55 minutes; this session averaged 140 bpm across 55 minutes — target not met
        FACT Next-session target: average heart rate at or under 131 bpm for about 55 minutes

        ### Main Set
        #### Recovery Context
        - Work samples in target zone: 96% (135-150 bpm)
    """.trimIndent()

    private fun facts(): SessionNumericFacts {
        val parsed = parseSessionNumericFacts(factsMarkdown)
        assertNotNull(parsed)
        return parsed!!
    }

    private fun validate(markdown: String): List<SessionNumericViolation> =
        validateSessionNumericContract(markdown, facts())

    @Test
    fun `parses the fact fields the checks need`() {
        val facts = facts()
        assertEquals(140, facts.averageBpm)
        assertEquals(154, facts.peakBpm)
        assertEquals(131, facts.nextTargetBpm)
        assertEquals(55, facts.nextTargetMinutes)
        assertEquals(131, facts.checkTargetBpm)
        assertEquals(55, facts.checkTargetMinutes)
        assertEquals(80, facts.wholeSessionZonePct)
        assertEquals(96, facts.workZonePct)
    }

    @Test
    fun `returns null without session fact lines`() {
        assertNull(parseSessionNumericFacts("# Some exercise\n- Sets: 3x8"))
    }

    @Test
    fun `clean insight produces no violations`() {
        val markdown = """
            ## What stood out
            - The session averaged 140 bpm, peak 154 bpm.
            - 80% of the whole session stayed inside the target zone.

            ## Next session target
            - Keep average heart rate at or under 131 bpm for about 55 minutes.
        """.trimIndent()
        assertTrue(validate(markdown).isEmpty())
    }

    @Test
    fun `flags average quoted as the peak value`() {
        val violations = validate("## What stood out\n- The session averaged 154 bpm.")
        assertEquals(1, violations.size)
        assertTrue(violations.single().correction.contains("average is 140 bpm"))
    }

    @Test
    fun `flags peak quoted as the average value`() {
        val violations = validate("## What stood out\n- Peak was 140 bpm.")
        assertEquals(1, violations.size)
        assertTrue(violations.single().correction.contains("peak is 154 bpm"))
    }

    @Test
    fun `skips scoped heart rate mentions`() {
        val markdown = """
            ## Exercise highlights
            - Rest HR peaked at 121 bpm and averaged 112 bpm.
            - During the main set the work average was 146 bpm.
        """.trimIndent()
        assertTrue(validate(markdown).isEmpty())
    }

    @Test
    fun `a peak value that is not the sibling average is not flagged`() {
        // Detection is limited to sibling swaps; other wrong peaks are the allowlist's problem.
        assertTrue(validate("## What stood out\n- Peak was 121 bpm.").isEmpty())
    }

    @Test
    fun `flags a target pair matching neither fact`() {
        val violations = validate("## Next session target\n- Keep average heart rate at or under 130 bpm for about 50 minutes.")
        assertEquals(1, violations.size)
        assertTrue(violations.single().correction.contains("at or under 131 bpm for about 55 minutes"))
    }

    @Test
    fun `accepts a target pair quoting the previous-target check`() {
        val markdown = "## What stood out\n- The target was at or under 131 bpm for about 55 minutes; not met."
        assertTrue(validate(markdown).isEmpty())
    }

    @Test
    fun `flags a whole-session zone claim quoting the work figure`() {
        val violations = validate("## What stood out\n- 96% of the whole session was inside the target zone.")
        assertEquals(1, violations.size)
        assertTrue(violations.single().correction.contains("80% of HR samples"))
    }

    @Test
    fun `flags a work-scope zone claim quoting the whole-session figure`() {
        val violations = validate("## Exercise highlights\n- 80% of work samples in the target zone.")
        assertEquals(1, violations.size)
        assertTrue(violations.single().correction.contains("96% of work-period samples"))
    }

    @Test
    fun `unqualified zone claims are not flagged`() {
        // Without a scope marker both 80% and 96% are legal readings; skip rather than guess.
        assertTrue(validate("## What stood out\n- 80% of HR samples in the target zone.").isEmpty())
        assertTrue(validate("## What stood out\n- 96% of HR samples in the target zone.").isEmpty())
    }

    @Test
    fun `violations are capped to keep the rewrite prompt short`() {
        val many = List(10) { "## What stood out\n- The session averaged 154 bpm." }.joinToString("\n")
        assertTrue(validate(many).size <= 4)
    }
}
