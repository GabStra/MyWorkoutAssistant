package com.gabstra.myworkoutassistant.shared.utils

import org.junit.Assert.assertEquals
import org.junit.Test

class SetComparisonTest {

    @Test
    fun `compareSetListsUnordered returns above when one of two sets improves and the other is unchanged`() {
        val previousSession = listOf(
            SimpleSet(weight = 100.0, reps = 10),
            SimpleSet(weight = 100.0, reps = 12)
        )
        val currentSession = listOf(
            SimpleSet(weight = 100.0, reps = 11),
            SimpleSet(weight = 100.0, reps = 12)
        )

        val result = compareSetListsUnordered(currentSession, previousSession)

        assertEquals(Ternary.ABOVE, result)
    }

    @Test
    fun `progression lifecycle returns above for planned load jump with rep reset`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 12))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 125.0),
            jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(defaultPct = 0.25),
        )
        val currentSession = DoubleProgressionHelper.planNextSession(
            previousSets = previousSession,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            jumpPolicy = config.jumpPolicy,
        ).sets
        assert(currentSession.single().weight > previousSession.single().weight)
        assert(currentSession.single().reps < previousSession.single().reps)

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.ABOVE, result)
    }

    @Test
    fun `progression lifecycle returns above for same load and more reps`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 10))
        val currentSession = listOf(SimpleSet(weight = 100.0, reps = 11))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 125.0),
            jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(defaultPct = 0.25),
        )

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.ABOVE, result)
    }

    @Test
    fun `progression lifecycle returns above for same reps and more load`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 10))
        val currentSession = listOf(SimpleSet(weight = 102.5, reps = 10))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 125.0),
            jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(defaultPct = 0.25),
        )

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.ABOVE, result)
    }

    @Test
    fun `progression lifecycle does not treat undershooting planned load jump as above`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 12))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 102.5),
        )
        val plannedSet = DoubleProgressionHelper.planNextSession(
            previousSets = previousSession,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            jumpPolicy = config.jumpPolicy,
        ).sets.single()
        val currentSession = listOf(plannedSet.copy(reps = plannedSet.reps - 1))

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.BELOW, result)
    }

    @Test
    fun `progression lifecycle allows overshooting planned load when planned reps are met`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 12))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 125.0),
            jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(defaultPct = 0.25),
        )
        val plannedSet = DoubleProgressionHelper.planNextSession(
            previousSets = previousSession,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            jumpPolicy = config.jumpPolicy,
        ).sets.single()
        val currentSession = listOf(plannedSet.copy(weight = plannedSet.weight + 5.0))

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.ABOVE, result)
    }

    @Test
    fun `progression lifecycle rejects overshooting planned load when planned reps are missed`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 12))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 125.0),
            jumpPolicy = DoubleProgressionHelper.LoadJumpPolicy(defaultPct = 0.25),
        )
        val plannedSet = DoubleProgressionHelper.planNextSession(
            previousSets = previousSession,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            jumpPolicy = config.jumpPolicy,
        ).sets.single()
        val currentSession = listOf(
            plannedSet.copy(weight = plannedSet.weight + 5.0, reps = plannedSet.reps - 1)
        )

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.BELOW, result)
    }

    @Test
    fun `progression lifecycle does not treat unplanned higher load and fewer reps as above`() {
        val previousSession = listOf(SimpleSet(weight = 100.0, reps = 10))
        val currentSession = listOf(SimpleSet(weight = 102.5, reps = 8))
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 102.5),
        )

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.BELOW, result)
    }

    @Test
    fun `progression lifecycle keeps true mixed sessions mixed`() {
        val previousSession = listOf(
            SimpleSet(weight = 100.0, reps = 12),
            SimpleSet(weight = 100.0, reps = 12),
        )
        val config = ProgressionLifecycleComparisonConfig(
            repsRange = 8..12,
            availableWeights = setOf(100.0, 102.5),
        )
        val plannedSets = DoubleProgressionHelper.planNextSession(
            previousSets = previousSession,
            availableWeights = config.availableWeights,
            repsRange = config.repsRange,
            jumpPolicy = config.jumpPolicy,
        ).sets
        val currentSession = listOf(
            plannedSets[0],
            plannedSets[1].copy(reps = plannedSets[1].reps - 1),
        )

        val result = compareSetListsForProgressionLifecycle(currentSession, previousSession, config)

        assertEquals(Ternary.MIXED, result)
    }
}
