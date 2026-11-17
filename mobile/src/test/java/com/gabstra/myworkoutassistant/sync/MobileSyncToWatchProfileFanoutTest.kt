package com.gabstra.myworkoutassistant.sync

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.profile.UserProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.LocalDate
import java.util.UUID

class MobileSyncToWatchProfileFanoutTest {

    @Test
    fun `global sync pins one ordered job per distinct profile without an active-profile fallback`() {
        val alice = UserProfile(id = "profile-alice", name = "Alice")
        val bob = UserProfile(id = "profile-bob", name = "Bob")
        val carol = UserProfile(id = "profile-carol", name = "Carol")

        val jobs = planProfileSyncJobs(listOf(alice, bob, carol, alice))

        assertEquals(listOf("profile-alice", "profile-bob", "profile-carol"), jobs.map { it.profileId })
        assertEquals(listOf("Alice", "Bob", "Carol"), jobs.map { it.profileName })
        assertEquals(listOf(false, false, true), jobs.map { it.isFinalJob })
        assertFalse(jobs.dropLast(1).any { it.isFinalJob })
        assertTrue(jobs.last().isFinalJob)
    }

    @Test
    fun `last profile backup retains shared archived workout and profile settings`() {
        val root = Files.createTempDirectory("profile-sync-fanout").toFile()
        try {
            val archived = Workout(
                id = UUID.randomUUID(),
                name = "Archived A workout",
                description = "",
                workoutComponents = emptyList(),
                order = 0,
                creationDate = LocalDate.of(2026, 1, 1),
                isActive = false,
                globalId = UUID.randomUUID(),
                type = 0,
            )
            val phoneA = WorkoutStoreRepository(File(root, "phone/a"), root)
            val phoneB = WorkoutStoreRepository(File(root, "phone/b"), root)
            phoneA.saveWorkoutStore(store(archived, weightKg = 60.0))
            phoneB.saveWorkoutStore(store(archived, weightKg = 82.5))

            val profileAStore = phoneA.getWorkoutStore()
            val profileBStore = phoneB.getWorkoutStore()
            val profileBEligibleWorkouts = profileBStore.workouts.filter { it.isActive }
            assertTrue(profileBEligibleWorkouts.isEmpty()) // B has no history for A's archived workout.

            val watchA = WorkoutStoreRepository(File(root, "watch/a"), File(root, "watch-shared"))
            val watchB = WorkoutStoreRepository(File(root, "watch/b"), File(root, "watch-shared"))
            watchA.saveWorkoutStore(adjustedWorkoutStoreForPhoneSync(profileAStore))
            watchB.saveWorkoutStore(adjustedWorkoutStoreForPhoneSync(profileBStore))

            assertEquals(listOf(archived.id), watchA.getWorkoutStore().workouts.map { it.id })
            assertEquals(listOf(archived.id), watchB.getWorkoutStore().workouts.map { it.id })
            assertEquals(60.0, watchA.getWorkoutStore().weightKg, 0.0)
            assertEquals(82.5, watchB.getWorkoutStore().weightKg, 0.0)
        } finally {
            root.deleteRecursively()
        }
    }

    private fun store(workout: Workout, weightKg: Double) = WorkoutStore(
        workouts = listOf(workout),
        birthDateYear = 0,
        weightKg = weightKg,
        progressionPercentageAmount = 0.0,
    )
}
