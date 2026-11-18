package com.gabstra.myworkoutassistant.shared

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.nio.file.Path
import java.time.LocalDate
import java.util.UUID

class WorkoutStoreRepositoryWorkoutPlanMembershipTest {

    private lateinit var directory: Path

    @Before
    fun setUp() {
        directory = Files.createTempDirectory("workout-store-plan-membership")
    }

    @After
    fun tearDown() {
        directory.toFile().deleteRecursively()
    }

    @Test
    fun saveDissolvesEveryUnassignedPlanAndPreservesWorkoutsPlansAndOrder() {
        val pushPlan = plan("Push", order = 2)
        val draftPlan = plan("Draft", order = 3)
        val firstSentinel = plan(UNASSIGNED_PLAN_NAME, order = 0)
        val secondSentinel = plan(UNASSIGNED_PLAN_NAME, order = 1)
        val unknownPlanId = UUID.randomUUID()
        val pushStaleClaimId = UUID.randomUUID()
        val firstLegacy = workout("Legacy A", firstSentinel.id, order = 0)
        val secondLegacy = workout("Legacy B", secondSentinel.id, order = 1)
        val pushWorkout = workout("Push day", pushPlan.id, order = 2)
        val noPlanWorkout = workout("No plan", null, order = 3)
        val unknownPlanWorkout = workout("Unknown plan", unknownPlanId, order = 4)
        val originalWorkouts =
            listOf(firstLegacy, secondLegacy, pushWorkout, noPlanWorkout, unknownPlanWorkout)

        val repository = WorkoutStoreRepository(directory.toFile())
        repository.saveWorkoutStore(
            store(
                workouts = originalWorkouts,
                plans = listOf(
                    firstSentinel.copy(workoutIds = listOf(UUID.randomUUID())),
                    secondSentinel.copy(workoutIds = emptyList()),
                    pushPlan.copy(workoutIds = listOf(pushStaleClaimId)),
                    draftPlan,
                ),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertEquals(listOf(pushPlan.id, draftPlan.id), loaded.workoutPlans.map { it.id })
        assertEquals(listOf("Push", "Draft"), loaded.workoutPlans.map { it.name })
        assertEquals(listOf(2, 3), loaded.workoutPlans.map { it.order })
        // A missing-workout reference is retained rather than silently dropped.
        assertEquals(
            listOf(pushStaleClaimId, pushWorkout.id),
            loaded.plan(pushPlan.id).workoutIds,
        )
        assertTrue(loaded.plan(draftPlan.id).workoutIds.isEmpty())
        assertEquals(originalWorkouts.map { it.id }, loaded.workouts.map { it.id })
        assertEquals(originalWorkouts.map { it.name }, loaded.workouts.map { it.name })
        assertEquals(originalWorkouts.map { it.order }, loaded.workouts.map { it.order })
        assertEquals(originalWorkouts.map { it.globalId }, loaded.workouts.map { it.globalId })
        assertEquals(firstLegacy.copy(workoutPlanId = null), loaded.workout(firstLegacy.id))
        assertEquals(secondLegacy.copy(workoutPlanId = null), loaded.workout(secondLegacy.id))
        assertEquals(pushWorkout, loaded.workout(pushWorkout.id))
        assertEquals(noPlanWorkout, loaded.workout(noPlanWorkout.id))
        assertEquals(unknownPlanWorkout, loaded.workout(unknownPlanWorkout.id))

        // Replaying the migration and another save/load round is a no-op (idempotent persistence).
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
        repository.saveWorkoutStore(loaded)
        assertEquals(loaded, repository.getWorkoutStore())
    }

    @Test
    fun loadDissolvesMultipleLegacyUnassignedPlansEvenWithStaleMembership() {
        val firstSentinel = plan(UNASSIGNED_PLAN_NAME, order = 7)
        val secondSentinel = plan(UNASSIGNED_PLAN_NAME, order = 8)
        val pushPlan = plan("Push", order = 1)
        val pushStaleClaimId = UUID.randomUUID()
        val firstLegacy = workout("First", firstSentinel.id)
        val secondLegacy = workout("Second", secondSentinel.id)
        val pushWorkout = workout("Push day", pushPlan.id)
        val staleStore = store(
            workouts = listOf(firstLegacy, secondLegacy, pushWorkout),
            plans = listOf(
                firstSentinel.copy(workoutIds = listOf(firstLegacy.id, UUID.randomUUID())),
                pushPlan.copy(workoutIds = listOf(pushStaleClaimId)),
                secondSentinel.copy(workoutIds = listOf(secondLegacy.id)),
            ),
        )
        directory.resolve("workout_store.json").toFile()
            .writeText(fromWorkoutStoreToJSON(staleStore))

        val repository = WorkoutStoreRepository(directory.toFile())
        val loaded = repository.getWorkoutStore()

        assertEquals(listOf(pushPlan.id), loaded.workoutPlans.map { it.id })
        assertEquals(
            listOf(pushStaleClaimId, pushWorkout.id),
            loaded.plan(pushPlan.id).workoutIds,
        )
        assertNull(loaded.workout(firstLegacy.id).workoutPlanId)
        assertNull(loaded.workout(secondLegacy.id).workoutPlanId)
        assertEquals(pushPlan.id, loaded.workout(pushWorkout.id).workoutPlanId)
        assertEquals(loaded, repository.getWorkoutStore())
    }

    @Test
    fun onlyTheExactNameIsReserved() {
        val nearMissNames = listOf(
            "unassigned",
            "Unassigned ",
            " Unassigned",
            "Unassigned 2",
            "My Unassigned",
        )
        val nearMissPlans = nearMissNames.mapIndexed { index, name -> plan(name, order = index) }
        val exactPlan = plan(UNASSIGNED_PLAN_NAME, order = nearMissNames.size)
        val nearMissWorkouts = nearMissPlans.map { nearMissPlan ->
            workout("For ${nearMissPlan.name}", nearMissPlan.id)
        }
        val exactWorkout = workout("For sentinel", exactPlan.id)

        WorkoutStoreRepository(directory.toFile()).saveWorkoutStore(
            store(
                workouts = nearMissWorkouts + exactWorkout,
                plans = nearMissPlans + exactPlan,
            )
        )

        val loaded = WorkoutStoreRepository(directory.toFile()).getWorkoutStore()

        assertEquals(nearMissPlans.map { it.id }, loaded.workoutPlans.map { it.id })
        assertEquals(nearMissNames, loaded.workoutPlans.map { it.name })
        nearMissPlans.zip(nearMissWorkouts).forEach { (plan, workout) ->
            assertEquals(listOf(workout.id), loaded.plan(plan.id).workoutIds)
            assertEquals(plan.id, loaded.workout(workout.id).workoutPlanId)
        }
        assertNull(loaded.workout(exactWorkout.id).workoutPlanId)
    }

    @Test
    fun savingFromJsonDissolvesUnassignedPlansWithoutCreatingAPlaceholder() {
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val solo = workout("Solo", sentinel.id)
        val json = fromWorkoutStoreToJSON(
            store(listOf(solo), listOf(sentinel.copy(workoutIds = listOf(UUID.randomUUID()))))
        )
        val repository = WorkoutStoreRepository(directory.toFile())

        repository.saveWorkoutStoreFromJson(json)

        val loaded = repository.getWorkoutStore()
        assertTrue(loaded.workoutPlans.isEmpty())
        assertNull(loaded.workout(solo.id).workoutPlanId)
        assertEquals(solo.name, loaded.workout(solo.id).name)
    }

    @Test
    fun savingFromJsonBackfillsUniquePlanOnlyMembership() {
        val pushPlan = plan("Push")
        val member = workout("Plan-only member", null)
        val json = fromWorkoutStoreToJSON(
            store(
                workouts = listOf(member),
                plans = listOf(pushPlan.copy(workoutIds = listOf(member.id))),
            )
        )
        val repository = WorkoutStoreRepository(directory.toFile())

        repository.saveWorkoutStoreFromJson(json)

        val loaded = repository.getWorkoutStore()
        assertEquals(pushPlan.id, loaded.workout(member.id).workoutPlanId)
        assertEquals(listOf(member.id), loaded.plan(pushPlan.id).workoutIds)
    }

    @Test
    fun splitStoreLoadAndSaveDissolveUnassignedPlansInSharedFile() {
        val personalDirectory = Files.createTempDirectory("workout-store-plan-personal")
        val sharedDirectory = Files.createTempDirectory("workout-store-plan-shared")
        try {
            val sentinel = plan(UNASSIGNED_PLAN_NAME)
            val pushPlan = plan("Push")
            val legacy = workout("Legacy", sentinel.id)
            val pushWorkout = workout("Push day", pushPlan.id)
            val repository = WorkoutStoreRepository(
                personalDirectory.toFile(),
                sharedDirectory.toFile(),
            )

            repository.saveWorkoutStore(
                store(listOf(legacy, pushWorkout), listOf(sentinel, pushPlan))
            )

            val loaded = repository.getWorkoutStore()
            assertEquals(listOf(pushPlan.id), loaded.workoutPlans.map { it.id })
            assertNull(loaded.workout(legacy.id).workoutPlanId)
            assertEquals(pushPlan.id, loaded.workout(pushWorkout.id).workoutPlanId)
            val sharedJson = File(sharedDirectory.toFile(), "workout_store.json").readText()
            assertTrue(!sharedJson.contains(UNASSIGNED_PLAN_NAME))
        } finally {
            personalDirectory.toFile().deleteRecursively()
            sharedDirectory.toFile().deleteRecursively()
        }
    }

    @Test
    fun loadKeepsMissingPlanReferencesWhilePreservingWorkoutAssociations() {
        val plan = plan("Push")
        val assigned = workout("Assigned", plan.id)
        val noPlan = workout("No plan", null)
        val unknownPlanId = UUID.randomUUID()
        val unknown = workout("Unknown", unknownPlanId)
        val missingWorkoutId = UUID.randomUUID()
        val staleStore = store(
            workouts = listOf(assigned, noPlan, unknown),
            plans = listOf(plan.copy(workoutIds = listOf(missingWorkoutId, assigned.id))),
        )
        Files.createDirectories(directory)
        directory.resolve("workout_store.json").toFile()
            .writeText(fromWorkoutStoreToJSON(staleStore))

        val loaded = WorkoutStoreRepository(directory.toFile()).getWorkoutStore()

        assertEquals(
            listOf(missingWorkoutId, assigned.id),
            loaded.workoutPlans.single().workoutIds,
        )
        assertEquals(plan.id, loaded.workout(assigned.id).workoutPlanId)
        assertNull(loaded.workout(noPlan.id).workoutPlanId)
        assertEquals(unknownPlanId, loaded.workout(unknown.id).workoutPlanId)
    }

    @Test
    fun loadPersistsConversionOfCurrentSchemaStoreToDisk() {
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val pushPlan = plan("Push")
        val legacy = workout("Legacy", sentinel.id)
        val pushWorkout = workout("Push day", pushPlan.id)
        val currentSchemaStore = store(
            workouts = listOf(legacy, pushWorkout),
            plans = listOf(sentinel, pushPlan),
        ).copy(schemaVersion = WorkoutStore.CURRENT_SCHEMA_VERSION)
        val storeFile = directory.resolve("workout_store.json").toFile()
        storeFile.writeText(fromWorkoutStoreToJSON(currentSchemaStore))

        val loaded = WorkoutStoreRepository(directory.toFile()).getWorkoutStore()

        assertEquals(listOf(pushPlan.id), loaded.workoutPlans.map { it.id })
        assertNull(loaded.workout(legacy.id).workoutPlanId)

        val diskStore = fromJSONToWorkoutStore(storeFile.readText())
        assertTrue(diskStore.workoutPlans.none { isReservedWorkoutPlanName(it.name) })
        assertNull(diskStore.workout(legacy.id).workoutPlanId)
        assertEquals(listOf(legacy.id, pushWorkout.id), diskStore.workouts.map { it.id })

        val recovery = File(directory.toFile(), "workout_store.json.pre-migration-recovery")
        assertTrue(recovery.exists())
        assertTrue(recovery.readText().contains(UNASSIGNED_PLAN_NAME))
    }

    @Test
    fun loadPersistsConversionOfCurrentSchemaSplitSharedFile() {
        val sharedDirectory = Files.createDirectories(directory.resolve("shared"))
        val personalDirectory = Files.createDirectories(directory.resolve("personal"))
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val legacy = workout("Legacy", sentinel.id)
        val sharedFile = File(sharedDirectory.toFile(), "workout_store.json")
        sharedFile.writeText(
            fromWorkoutStoreToJSON(
                store(listOf(legacy), listOf(sentinel))
                    .copy(schemaVersion = WorkoutStore.CURRENT_SCHEMA_VERSION)
            )
        )
        File(personalDirectory.toFile(), "workout_store.json")
            .writeText(fromWorkoutStoreToJSON(store(emptyList(), emptyList())))

        val loaded = WorkoutStoreRepository(
            personalDirectory.toFile(),
            sharedDirectory.toFile(),
        ).getWorkoutStore()

        assertNull(loaded.workout(legacy.id).workoutPlanId)
        val diskStore = fromJSONToWorkoutStore(sharedFile.readText())
        assertTrue(diskStore.workoutPlans.isEmpty())
        assertNull(diskStore.workout(legacy.id).workoutPlanId)
        assertEquals(listOf(legacy.id), diskStore.workouts.map { it.id })
    }

    @Test
    fun fullRestoreSharedUnionSurvivesPerProfilePersonalSaves() {
        val sharedDirectory = Files.createDirectories(directory.resolve("shared"))
        val profileADirectory = Files.createDirectories(directory.resolve("profiles/a"))
        val profileBDirectory = Files.createDirectories(directory.resolve("profiles/b"))
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val pushPlan = plan("Push")
        val archivedWorkout = workout("Archived", sentinel.id)
        val activeWorkout = workout("Active", pushPlan.id)
        val unionStore = store(
            workouts = listOf(archivedWorkout, activeWorkout),
            plans = listOf(sentinel, pushPlan),
        )
        val profileARepository = WorkoutStoreRepository(
            profileADirectory.toFile(),
            sharedDirectory.toFile(),
        )
        val profileBRepository = WorkoutStoreRepository(
            profileBDirectory.toFile(),
            sharedDirectory.toFile(),
        )

        profileARepository.saveSharedContent(unionStore)
        profileARepository.savePersonalSettings(unionStore.copy(weightKg = 70.0))
        profileBRepository.savePersonalSettings(unionStore.copy(weightKg = 95.0))

        val sharedFile = File(sharedDirectory.toFile(), "workout_store.json")
        val sharedDiskStore = fromJSONToWorkoutStore(sharedFile.readText())
        assertEquals(
            listOf(archivedWorkout.id, activeWorkout.id),
            sharedDiskStore.workouts.map { it.id },
        )
        assertNull(sharedDiskStore.workout(archivedWorkout.id).workoutPlanId)
        assertEquals(listOf(pushPlan.id), sharedDiskStore.workoutPlans.map { it.id })

        val profileAStore = profileARepository.getWorkoutStore()
        val profileBStore = profileBRepository.getWorkoutStore()
        assertEquals(70.0, profileAStore.weightKg, 0.0)
        assertEquals(95.0, profileBStore.weightKg, 0.0)
        assertTrue(profileAStore.workouts.any { it.id == archivedWorkout.id })
        assertTrue(profileBStore.workouts.any { it.id == archivedWorkout.id })
    }

    @Test
    fun workoutsWithoutPlansDoNotCreateASentinelPlan() {
        val solo = workout("Solo", null)
        WorkoutStoreRepository(directory.toFile())
            .saveWorkoutStore(store(listOf(solo), plans = emptyList()))

        val loaded = WorkoutStoreRepository(directory.toFile()).getWorkoutStore()

        assertTrue(loaded.workoutPlans.isEmpty())
        assertNull(loaded.workout(solo.id).workoutPlanId)
    }

    @Test
    fun loadBackfillsUniquePlanClaimForNullWorkoutPlanId() {
        val pushPlan = plan("Push")
        val member = workout("Plan-only member", null)
        val repository = repositoryFor(
            store(
                workouts = listOf(member),
                plans = listOf(pushPlan.copy(workoutIds = listOf(member.id))),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertEquals(pushPlan.id, loaded.workout(member.id).workoutPlanId)
        assertEquals(listOf(member.id), loaded.plan(pushPlan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun loadBackfillsUniquePlanClaimForUnknownWorkoutPlanId() {
        val pushPlan = plan("Push")
        val unknownPlanId = UUID.randomUUID()
        val member = workout("Plan-only member", unknownPlanId)
        val repository = repositoryFor(
            store(
                workouts = listOf(member),
                plans = listOf(pushPlan.copy(workoutIds = listOf(member.id))),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertEquals(pushPlan.id, loaded.workout(member.id).workoutPlanId)
        assertEquals(listOf(member.id), loaded.plan(pushPlan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun loadKeepsValidWorkoutPlanIdWhenAnotherPlanAlsoClaimsTheWorkout() {
        val ownerPlan = plan("Owner")
        val conflictingPlan = plan("Conflicting")
        val member = workout("Owned", ownerPlan.id)
        val repository = repositoryFor(
            store(
                workouts = listOf(member),
                plans = listOf(
                    ownerPlan.copy(workoutIds = listOf(member.id)),
                    conflictingPlan.copy(workoutIds = listOf(member.id)),
                ),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertEquals(ownerPlan.id, loaded.workout(member.id).workoutPlanId)
        assertEquals(listOf(member.id), loaded.plan(ownerPlan.id).workoutIds)
        // The losing claim is preserved as conflict evidence instead of silently erased.
        assertEquals(listOf(member.id), loaded.plan(conflictingPlan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun loadLeavesWorkoutAmbiguousWhenMultiplePlansClaimIt() {
        val firstPlan = plan("First")
        val secondPlan = plan("Second")
        val member = workout("Ambiguous", null)
        val repository = repositoryFor(
            store(
                workouts = listOf(member),
                plans = listOf(
                    firstPlan.copy(workoutIds = listOf(member.id)),
                    secondPlan.copy(workoutIds = listOf(member.id)),
                ),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertNull(loaded.workout(member.id).workoutPlanId)
        assertEquals(listOf(member.id), loaded.plan(firstPlan.id).workoutIds)
        assertEquals(listOf(member.id), loaded.plan(secondPlan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun loadPreservesMissingWorkoutReferencesWithoutRewritingThePlanList() {
        val plan = plan("Push")
        val missingWorkoutId = UUID.randomUUID()
        val repository = repositoryFor(
            store(
                workouts = emptyList(),
                plans = listOf(plan.copy(workoutIds = listOf(missingWorkoutId))),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertEquals(listOf(missingWorkoutId), loaded.plan(plan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun explicitDetachIsNotReattachedByAStalePlanClaim() {
        val pushPlan = plan("Push")
        val detached = workout("Detached", pushPlan.id)
        val store = store(
            workouts = listOf(detached.copy(workoutPlanId = null)),
            plans = listOf(pushPlan.copy(workoutIds = listOf(detached.id))),
        )

        val synchronized = store.synchronizeWorkoutPlanMemberships()
        val converted = store.convertUnassignedPlansToUngroupedWorkouts()

        listOf(synchronized, converted).forEach { result ->
            assertNull(result.workout(detached.id).workoutPlanId)
            assertTrue(result.plan(pushPlan.id).workoutIds.isEmpty())
        }
    }

    @Test
    fun loadConvertsReservedPlaceholderOnlyMembershipToUngrouped() {
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val nullPlanWorkout = workout("Null plan", null)
        val stalePlanWorkout = workout("Stale plan", UUID.randomUUID())
        val repository = repositoryFor(
            store(
                workouts = listOf(nullPlanWorkout, stalePlanWorkout),
                plans = listOf(
                    sentinel.copy(
                        workoutIds = listOf(nullPlanWorkout.id, stalePlanWorkout.id),
                    )
                ),
            )
        )

        val loaded = repository.getWorkoutStore()

        assertTrue(loaded.workoutPlans.isEmpty())
        assertNull(loaded.workout(nullPlanWorkout.id).workoutPlanId)
        assertNull(loaded.workout(stalePlanWorkout.id).workoutPlanId)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun loadPreservesUnambiguousPlanOnlyClaimButNotExplicitReservedOwnership() {
        val sentinel = plan(UNASSIGNED_PLAN_NAME)
        val realPlan = plan("3-Days Plan")
        val nullPlanWorkout = workout("Null plan", null)
        val sentinelPlanWorkout = workout("Sentinel plan", sentinel.id)
        val repository = repositoryFor(
            store(
                workouts = listOf(nullPlanWorkout, sentinelPlanWorkout),
                plans = listOf(
                    sentinel.copy(
                        workoutIds = listOf(nullPlanWorkout.id, sentinelPlanWorkout.id),
                    ),
                    realPlan.copy(
                        workoutIds = listOf(nullPlanWorkout.id, sentinelPlanWorkout.id),
                    ),
                ),
            )
        )
        val loaded = repository.getWorkoutStore()

        assertEquals(listOf(realPlan.id), loaded.workoutPlans.map { it.id })
        assertEquals(realPlan.id, loaded.workout(nullPlanWorkout.id).workoutPlanId)
        assertNull(loaded.workout(sentinelPlanWorkout.id).workoutPlanId)
        // The stale real-plan claim cannot be retained or the next migration would reattach it.
        assertEquals(listOf(nullPlanWorkout.id), loaded.plan(realPlan.id).workoutIds)
        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
    }

    @Test
    fun explicitReservedOwnershipWinsOverConflictingRealPlanAndStaysUngrouped() {
        val sentinel = plan(UNASSIGNED_PLAN_NAME, order = 0)
        val realPlan = plan("Push", order = 1)
        val legacy = workout("Legacy", sentinel.id, order = 0)
        val pushWorkout = workout("Push day", realPlan.id, order = 1)
        val staleStore = store(
            workouts = listOf(legacy, pushWorkout),
            plans = listOf(
                sentinel.copy(workoutIds = listOf(legacy.id)),
                realPlan.copy(workoutIds = listOf(legacy.id, pushWorkout.id)),
            ),
        )
        val repository = repositoryFor(staleStore)

        val loaded = repository.getWorkoutStore()

        assertEquals(listOf(realPlan.id), loaded.workoutPlans.map { it.id })
        assertNull(loaded.workout(legacy.id).workoutPlanId)
        assertEquals(realPlan.id, loaded.workout(pushWorkout.id).workoutPlanId)
        assertEquals(listOf(pushWorkout.id), loaded.plan(realPlan.id).workoutIds)
        assertEquals(legacy.name, loaded.workout(legacy.id).name)
        assertEquals(legacy.globalId, loaded.workout(legacy.id).globalId)

        val recovery = File(directory.toFile(), "workout_store.json.pre-migration-recovery")
        assertTrue(recovery.exists())
        val evidence = fromJSONToWorkoutStore(recovery.readText())
        assertEquals(sentinel.id, evidence.workout(legacy.id).workoutPlanId)
        assertEquals(
            listOf(legacy.id, pushWorkout.id),
            evidence.plan(realPlan.id).workoutIds,
        )
        assertTrue(evidence.workoutPlans.any { isReservedWorkoutPlanName(it.name) })

        assertEquals(loaded, repository.migrateWorkoutStore(loaded))
        repository.saveWorkoutStore(loaded)
        assertEquals(loaded, repository.getWorkoutStore())
        repository.saveWorkoutStore(loaded)
        assertEquals(loaded, repository.getWorkoutStore())
    }

    private fun WorkoutStore.workout(id: UUID): Workout = workouts.single { it.id == id }

    private fun WorkoutStore.plan(id: UUID): WorkoutPlan = workoutPlans.single { it.id == id }

    private fun repositoryFor(store: WorkoutStore): WorkoutStoreRepository {
        directory.resolve("workout_store.json").toFile()
            .writeText(fromWorkoutStoreToJSON(store))
        return WorkoutStoreRepository(directory.toFile())
    }

    private fun plan(name: String, order: Int = 0) = WorkoutPlan(
        id = UUID.randomUUID(),
        name = name,
        workoutIds = emptyList(),
        order = order,
    )

    private fun workout(name: String, workoutPlanId: UUID?, order: Int = 0) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = "",
        workoutComponents = emptyList(),
        order = order,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        workoutPlanId = workoutPlanId,
    )

    private fun store(workouts: List<Workout>, plans: List<WorkoutPlan>) = WorkoutStore(
        workouts = workouts,
        workoutPlans = plans,
        birthDateYear = 1990,
        weightKg = 80.0,
        progressionPercentageAmount = 0.0,
    )
}
