package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import android.content.Intent
import android.view.accessibility.AccessibilityWindowInfo
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.ComposeTimeoutException
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.longClick
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextClearance
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.RecurringWorkoutAuthoring
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.LoadHistoryPolicy
import java.time.LocalDate
import java.io.File
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RecurringControlsAuthoringE2ETest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    @Test
    fun authorRecurringFamily_preserveModeTrackAndPolicyAcrossReopen() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val originalProfileId = Profiles.activeProfileId(context)
        val profileId = Profiles.create(context, "Recurring controls E2E").id
        check(Profiles.setLocallyChosenProfile(context, profileId))
        val repository = WorkoutStoreRepository.forActiveProfile(context)
        val testPlanId = UUID.randomUUID()
        val baseWorkoutId = UUID.randomUUID()
        val secondWorkoutId = UUID.randomUUID()
        val suffix = UUID.randomUUID().toString().take(8)
        val testName = "Recurring UI " + suffix
        val secondName = "Recurring UI other " + suffix
        val exerciseName = "Recurring Slot " + suffix
        val secondExerciseName = "Recurring Other Slot " + suffix
        val planName = "Recurring Plan " + suffix
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        var addedEquipmentId: UUID? = null
        var scenario: ActivityScenario<MainActivity>? = null

        try {
            val fixture = CrossDeviceSyncPhoneWorkoutStoreFixture.createWorkoutStore()
            val templateWorkout = fixture.workouts.first()
            val templateExercise = templateWorkout.workoutComponents.filterIsInstance<Exercise>().first()
            val exercise = templateExercise.copy(
                id = UUID.randomUUID(),
                name = exerciseName,
                notes = "",
                sets = templateExercise.sets.filterIsInstance<WeightSet>().map {
                    it.copy(id = UUID.randomUUID())
                },
                movementRef = null,
                exerciseDefinitionId = null,
                recurringExerciseId = null,
                loadHistoryPolicy = LoadHistoryPolicy.NONE,
            )
            val secondExercise = exercise.copy(
                id = UUID.randomUUID(),
                name = secondExerciseName,
                sets = exercise.sets.filterIsInstance<WeightSet>().map { it.copy(id = UUID.randomUUID()) },
                recurringExerciseId = null,
                loadHistoryPolicy = LoadHistoryPolicy.NONE,
            )
            val before = repository.getWorkoutStore()
            addedEquipmentId = fixture.equipments.firstOrNull()?.id
                ?.takeIf { id -> before.equipments.none { it.id == id } }
            val testWorkout = templateWorkout.copy(
                id = baseWorkoutId,
                name = testName,
                description = "Temporary recurring controls UI test",
                workoutComponents = listOf(exercise),
                order = (before.workouts.maxOfOrNull { it.order } ?: -1) + 1,
                creationDate = LocalDate.now(),
                previousVersionId = null,
                nextVersionId = null,
                globalId = UUID.randomUUID(),
                workoutPlanId = testPlanId,
                recurringSessionId = null,
                prescriptionOrdinal = null,
                prescriptionLabel = null,
            )
            val testPlan = WorkoutPlan(
                id = testPlanId,
                name = planName,
                workoutIds = listOf(baseWorkoutId, secondWorkoutId),
                order = (before.workoutPlans.maxOfOrNull { it.order } ?: -1) + 1,
            )
            val secondWorkout = testWorkout.copy(
                id = secondWorkoutId,
                name = secondName,
                description = "Second independent recurring-family UI fixture",
                workoutComponents = listOf(secondExercise),
                order = testWorkout.order + 1,
                globalId = UUID.randomUUID(),
            )
            repository.saveWorkoutStore(before.copy(
                workouts = before.workouts + testWorkout + secondWorkout,
                equipments = (before.equipments + fixture.equipments).distinctBy { it.id },
                workoutPlans = before.workoutPlans + testPlan,
            ))

            scenario = ActivityScenario.launch(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            )
            val driver = PhoneAppDriver(device, context)
            driver.dismissStartupPermissionDialogs()
            waitForWorkoutsScreen(context, device, driver)
            if (hasComposeText("Workout Plan:")) {
                clickText(device, "Workout Plan:")
                clickText(device, planName)
            }

            assertWorkoutsHasNoPlanSettingsAction()
            openPlanSettings(testPlanId)
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").assertIsOn()
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").performClick()
            clickText(device, "Cancel")
            composeRule.waitUntil(10_000) { !hasComposeText("Plan settings") }
            waitForStore(repository) {
                it.workoutPlans.firstOrNull { plan -> plan.id == testPlanId }?.suggestNextPrescription == true
            }

            clickTag("edit_plan_${testPlanId}")
            waitForText("Plan settings")
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").assertIsOn()
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").performClick()
            clickText(device, "Save")
            waitForStore(repository) { store ->
                store.workoutPlans.firstOrNull { it.id == testPlanId }?.suggestNextPrescription == false
            }

            clickTag("edit_plan_${testPlanId}")
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").assertIsOff()
            clickText(device, "Cancel")
            composeRule.waitUntil(10_000) { !hasComposeText("Plan settings") }
            device.pressBack()
            composeRule.waitUntil(10_000) { hasComposeText("Workouts") }
            assertWorkoutsHasNoPlanSettingsAction()

            waitForDescription("Open workout: $testName").performClick()
            waitForText(testName)
            waitForDescription("More").performClick()
            clickTag("start_recurring_session")
            waitForStore(repository) {
                it.workouts.firstOrNull { workout -> workout.id == baseWorkoutId }?.recurringSessionId != null
            }
            val storedAfterStart = repository.getWorkoutStore().workouts
            val expectedBase = storedAfterStart.singleOrNull { it.id == baseWorkoutId }
            assertNotNull("Started family did not retain the fixture base workout id=$baseWorkoutId; storedIds=${storedAfterStart.map { it.id }}", expectedBase)
            val baseAfterStart = requireNotNull(expectedBase)
            assertTrue("The fixture base prescription should stay active after starting a recurring session.", baseAfterStart.isActive)
            val startedSessionId = requireNotNull(baseAfterStart.recurringSessionId)
            val createdFamily = storedAfterStart.filter { it.recurringSessionId == baseAfterStart.recurringSessionId }
            val familyDebug = createdFamily.joinToString { workout ->
                "id=${workout.id}, global=${workout.globalId}, active=${workout.isActive}, " +
                    "session=${workout.recurringSessionId}, ordinal=${workout.prescriptionOrdinal}, label=${workout.prescriptionLabel}"
            }
            composeRule.waitForIdle()
            driver.dismissStartupPermissionDialogs(timeoutMs = 1_000)
            driver.grantHealthConnectPermissionsForE2E(timeoutMs = 10_000)
            device.pressBack()
            composeRule.waitForIdle()
            waitForWorkoutsList(startedSessionId)
            assertWorkoutsShowsSingleSession(startedSessionId, baseWorkoutId)

            waitForDescription("Open workout: $secondName").performClick()
            waitForText(secondName)
            waitForDescription("More").performClick()
            clickTag("start_recurring_session")
            waitForStore(repository) {
                it.workouts.firstOrNull { workout -> workout.id == secondWorkoutId }?.recurringSessionId != null
            }
            val secondSessionId = requireNotNull(
                repository.getWorkoutStore().workouts.firstOrNull { it.id == secondWorkoutId }?.recurringSessionId,
            )
            assertNotEquals("The independent fixture workout joined the first session.", startedSessionId, secondSessionId)
            // Starting this second family from its workout detail may leave an
            // intermediate detail route on the stack. Return to the root list
            // through the visible breadcrumb; the prescription-detail Back path
            // is asserted separately below.
            clickText(device, "Workouts")
            composeRule.waitForIdle()
            waitForWorkoutsList(startedSessionId)
            device.takeScreenshot(File(context.cacheDir, "session-list-root.png"))
            assertWorkoutsShowsSingleSession(secondSessionId, secondWorkoutId)
            clickTag("recurring_session_${secondSessionId}")
            waitForTag("session_prescriptions_${secondSessionId}")
            waitForTag("prescription_${secondWorkoutId}").assertIsDisplayed()
            waitForTextPresence(secondName)
            check(composeRule.onAllNodes(hasTestTag("prescription_${baseWorkoutId}"), useUnmergedTree = true)
                .fetchSemanticsNodes().isEmpty()) {
                "Session B opened with a prescription from session A."
            }
            clickTag("session_back_to_workouts")
            waitForWorkoutsList(startedSessionId)
            clickTag("recurring_session_${startedSessionId}")
            waitForTag("session_prescriptions_${startedSessionId}")
            waitForTag("prescription_${baseWorkoutId}").assertIsDisplayed()
            check(composeRule.onAllNodes(hasTestTag("prescription_${secondWorkoutId}"), useUnmergedTree = true)
                .fetchSemanticsNodes().isEmpty()) {
                "Session A opened with a prescription from session B."
            }
            waitForTextPresence(testName)
            openSessionPrescriptionManager(startedSessionId, baseWorkoutId)
            waitForTag("make_standalone_workout_${baseWorkoutId}").performScrollTo().assertIsDisplayed()
            setTaggedEditText("prescription_label_${baseWorkoutId}", 0, "Discard this draft", familyDebug)
            dismissKeyboardIfVisible(device)
            clickTag("cancel_recurring_session")
            assertRecurringManagerClosed()
            waitForStore(repository) {
                it.workouts.firstOrNull { workout -> workout.id == baseWorkoutId }?.prescriptionLabel == null
            }
            openSessionPrescriptionManager(startedSessionId, baseWorkoutId)
            setTaggedEditText("prescription_label_${baseWorkoutId}", 0, "Foundation", familyDebug)
            dismissKeyboardIfVisible(device)
            clickTagged("save_prescription_${baseWorkoutId}", 0)
            assertRecurringManagerClosed()
            waitForStore(repository) {
                it.workouts.firstOrNull { workout -> workout.id == baseWorkoutId }?.prescriptionLabel == "Foundation"
            }
            waitForTag("session_prescriptions_${startedSessionId}")
            waitForTag("prescription_${baseWorkoutId}")
            composeRule.waitForIdle()
            waitForTextPresence(testName)
            device.takeScreenshot(File(context.cacheDir, "session-prescriptions.png"))

            clickTag("add_prescription")
            waitForText("Prescription 2 · $testName")
            clickText(device, exerciseName)
            waitForDescription("More").performClick()
            clickText(device, "Edit Exercise")
            waitForText("Edit exercise")
            val initialSessionId = requireNotNull(
                repository.getWorkoutStore().workouts.firstOrNull { it.id == baseWorkoutId }?.recurringSessionId
            )
            waitForStore(repository) { store ->
                store.workouts.count { it.recurringSessionId == initialSessionId } == 2
            }
            val initialFamily = repository.getWorkoutStore().workouts
                .filter { it.recurringSessionId == initialSessionId }
            assertEquals("The fixture family should contain exactly the base and its clone.", 2, initialFamily.size)
            val initialBase = exerciseByName(initialFamily.single { it.id == baseWorkoutId }, exerciseName)
            val initialCloneWorkout = initialFamily.first { it.id != baseWorkoutId }
            val initialCloneWorkoutId = initialCloneWorkout.id
            val initialClone = exerciseByName(initialCloneWorkout, exerciseName)
            assertEquals(LoadHistoryPolicy.LAST_WORKING_LOAD, initialBase.loadHistoryPolicy)
            assertEquals("A clone must inherit the source's selected behavior.",
                LoadHistoryPolicy.LAST_WORKING_LOAD, initialClone.loadHistoryPolicy)
            assertEquals(initialBase.exerciseDefinitionId, initialClone.exerciseDefinitionId)
            val originalTrackId = requireNotNull(
                initialBase.recurringExerciseId
            )
            waitForDescriptionContains("Weight behavior Last working load", scroll = true)
            clickTag("recurring_starting_load", scroll = true)
            clickPopupText("Prescribed weight")
            waitForDescriptionContains("Weight behavior Prescribed weight", scroll = true)
            clickTag("recurring_weight_history_slot", scroll = true)
            clickPopupText("No history link")
            waitForText("Save", scroll = true)
            check(clickTextAction(device, "Save"))
            device.waitForIdle()
            assertExerciseEditorClosed(device)

            waitForStore(repository) { store ->
                store.workouts.firstOrNull { it.id == initialCloneWorkoutId }
                    ?.let { exerciseByNameOrNull(it, exerciseName) }
                    ?.let {
                        it.recurringExerciseId == null && it.loadHistoryPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT
                    } == true
            }
            val afterUnlinkSave = exerciseByName(
                requireNotNull(repository.getWorkoutStore().workouts.firstOrNull { it.id == initialCloneWorkoutId }),
                exerciseName,
            )
            assertNull("Saving an unrelated note must keep the exercise unlinked.", afterUnlinkSave.recurringExerciseId)
            assertEquals(LoadHistoryPolicy.PRESCRIBED_WEIGHT, afterUnlinkSave.loadHistoryPolicy)

            waitForDescription("More").performClick()
            clickText(device, "Edit Exercise")
            waitForText("Edit exercise")
            waitForDescriptionContains("Weight history slot No history link", scroll = true)
            waitForDescriptionContains("Weight behavior Prescribed weight", scroll = true)
            waitForText("Save", scroll = true)
            check(clickTextAction(device, "Save"))
            device.waitForIdle()
            assertExerciseEditorClosed(device)
            waitForStore(repository) { store ->
                store.workouts.firstOrNull { it.id == initialCloneWorkoutId }
                    ?.let { exerciseByNameOrNull(it, exerciseName) }
                    ?.let {
                        it.recurringExerciseId == null && it.loadHistoryPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT
                    } == true
            }

            waitForDescription("More").performClick()
            clickText(device, "Edit Exercise")
            waitForText("Edit exercise")
            clickTag("recurring_weight_history_slot", scroll = true)
            clickPopupText("Create new weight history slot")
            waitForDescriptionContains("Weight behavior Prescribed weight", scroll = true)
            waitForText("Save", scroll = true)
            check(clickTextAction(device, "Save"))
            device.waitForIdle()
            assertExerciseEditorClosed(device)

            waitForStore(repository) { store ->
                store.workouts.firstOrNull { it.id == initialCloneWorkoutId }
                    ?.let { exerciseByNameOrNull(it, exerciseName) }
                    ?.let {
                        it.recurringExerciseId != null && it.recurringExerciseId != originalTrackId &&
                            it.loadHistoryPolicy == LoadHistoryPolicy.PRESCRIBED_WEIGHT
                    } == true
            }

            val afterNewTrack = repository.getWorkoutStore().workouts
                .filter { it.recurringSessionId == initialSessionId }
            val newTrackExercise = exerciseByName(
                requireNotNull(afterNewTrack.firstOrNull { it.id == initialCloneWorkoutId }),
                exerciseName,
            )
            assertNotEquals(originalTrackId, newTrackExercise.recurringExerciseId)
            assertNotNull(newTrackExercise.recurringExerciseId)
            assertEquals(LoadHistoryPolicy.PRESCRIBED_WEIGHT, newTrackExercise.loadHistoryPolicy)

            waitForDescription("More").performClick()
            clickText(device, "Edit Exercise")
            waitForText("Edit exercise")
            clickTag("recurring_weight_history_slot", scroll = true)
            val liveFamily = repository.getWorkoutStore().workouts.filter {
                it.recurringSessionId == initialSessionId
            }
            val liveBase = liveFamily.single { it.id == baseWorkoutId }
            val liveClone = liveFamily.single { it.id == initialCloneWorkoutId }
            val liveBaseExercise = exerciseByName(liveBase, exerciseName)
            val liveCloneExercise = exerciseByName(liveClone, exerciseName)
            val choices = RecurringWorkoutAuthoring.compatibleTrackChoices(liveCloneExercise, liveFamily)
            val sourceChoices = choices.filter { it.trackId == originalTrackId }
            check(sourceChoices.size == 1) {
                "Expected exactly one compatible choice for track $originalTrackId; found ${sourceChoices.size}: $choices"
            }
            val sourceChoice = sourceChoices.first()
            val choiceLabel = sourceChoice?.let { choice ->
                val prescription = choice.prescriptionLabel?.takeIf(String::isNotBlank)
                    ?: "Prescription ${choice.prescriptionOrdinal.takeIf { it > 0 } ?: "?"}"
                "${choice.exerciseName} · ${choice.sourceWorkoutName} · $prescription · Exercise ${choice.exercisePosition}"
            }
            check(choiceLabel != null) {
                "The source history slot is no longer compatible after editing. " +
                    "Initial signature=${exerciseTrackSignature(initialFamily, initialSessionId, exerciseName)}; " +
                    "current signature=${exerciseTrackSignature(liveFamily, initialSessionId, exerciseName)}; " +
                    "choices=$choices"
            }
            val uiTrackChoices = composeRule.onAllNodes(hasText("Exercise", substring = true), useUnmergedTree = true)
                .fetchSemanticsNodes()
            val matchingChoiceCount = composeRule.onAllNodes(hasText(choiceLabel), useUnmergedTree = true)
                .fetchSemanticsNodes().size
            check(matchingChoiceCount == 1) {
                "Expected one visible option for the source history slot '$choiceLabel', found " +
                    "$matchingChoiceCount. UI candidates=${uiTrackChoices.joinToString { it.config.toString() }}; " +
                    "initial signature=${exerciseTrackSignature(initialFamily, initialSessionId, exerciseName)}; " +
                    "current signature=${exerciseTrackSignature(liveFamily, initialSessionId, exerciseName)}; choices=$choices"
            }
            composeRule.onNodeWithText(choiceLabel, useUnmergedTree = true).performClick()
            clickTag("recurring_starting_load", scroll = true)
            clickPopupText("Last working load")
            waitForText("Save", scroll = true)
            check(clickTextAction(device, "Save"))
            device.waitForIdle()
            assertExerciseEditorClosed(device)

            waitForStore(repository) { store ->
                store.workouts.firstOrNull { it.id == initialCloneWorkoutId }
                    ?.let { exerciseByNameOrNull(it, exerciseName) }
                    ?.let {
                        it.recurringExerciseId == originalTrackId &&
                            it.loadHistoryPolicy == LoadHistoryPolicy.LAST_WORKING_LOAD
                    } == true
            }

            val savedAfterExerciseEdit = repository.getWorkoutStore()
            val sessionId = requireNotNull(
                savedAfterExerciseEdit.workouts.firstOrNull { it.id == baseWorkoutId }?.recurringSessionId
            )
            val family = savedAfterExerciseEdit.workouts.filter { it.recurringSessionId == sessionId }
            val baseAfterClone = family.single { it.id == baseWorkoutId }
            val clone = family.single { it.id == initialCloneWorkoutId }
            val baseExercise = exerciseByName(baseAfterClone, exerciseName)
            val clonedExercise = exerciseByName(clone, exerciseName)
            assertEquals(originalTrackId, clonedExercise.recurringExerciseId)
            assertEquals(baseExercise.recurringExerciseId, clonedExercise.recurringExerciseId)
            assertEquals(LoadHistoryPolicy.LAST_WORKING_LOAD, clonedExercise.loadHistoryPolicy)
            assertNotNull(clonedExercise.recurringExerciseId)

            waitForDescription("More").performClick()
            clickText(device, "Edit Exercise")
            waitForText("Edit exercise")
            assertTrue(
                waitForDescriptionContains("Weight history slot " + choiceLabel, scroll = true)
                    .contains("Foundation")
            )
            assertTrue(
                waitForDescriptionContains("Weight behavior Last working load", scroll = true)
                    .contains("Last working load")
            )
            device.pressBack()
            waitForTextPresence(exerciseName)
            device.pressBack()
            device.pressBack()
            composeRule.waitUntil(10_000) {
                composeRule.onAllNodes(hasTestTag("session_prescriptions_${sessionId}"), useUnmergedTree = true)
                    .fetchSemanticsNodes().isNotEmpty()
            }
            waitForTag("session_prescriptions_${sessionId}")
            openSessionPrescriptionManager(sessionId, initialCloneWorkoutId)
            setTaggedEditText("prescription_label_${initialCloneWorkoutId}", 0, "Progression")
            dismissKeyboardIfVisible(device)
            clickTagged("save_prescription_${initialCloneWorkoutId}", 0)
            assertRecurringManagerClosed()
            waitForStore(repository) { store ->
                val familyWorkouts = store.workouts.filter { it.recurringSessionId == sessionId }
                familyWorkouts.firstOrNull { it.id == baseWorkoutId }?.prescriptionLabel == "Foundation" &&
                    familyWorkouts.firstOrNull { it.id == initialCloneWorkoutId }?.prescriptionLabel == "Progression"
            }
            assertEquals(
                listOf(baseWorkoutId, initialCloneWorkoutId),
                repository.getWorkoutStore().workouts
                    .filter { it.recurringSessionId == sessionId }
                    .sortedBy { it.prescriptionOrdinal }
                    .map { it.id },
            )
            val planOrderById = repository.getWorkoutStore().workouts
                .filter { it.recurringSessionId == sessionId }
                .associate { it.id to it.order }
            dragPrescriptionBefore(initialCloneWorkoutId, baseWorkoutId)
            composeRule.waitForIdle()
            val unchangedOrder = repository.getWorkoutStore().workouts
                .filter { it.recurringSessionId == sessionId }
                .sortedBy { it.prescriptionOrdinal }
            assertEquals(listOf(baseWorkoutId, initialCloneWorkoutId), unchangedOrder.map { it.id })

            movePrescriptionUp(initialCloneWorkoutId)
            waitForStore(repository) { store ->
                val ordered = store.workouts.filter { it.recurringSessionId == sessionId }
                    .sortedBy { it.prescriptionOrdinal }
                ordered.size == 2 && ordered.map { it.id } == listOf(initialCloneWorkoutId, baseWorkoutId) &&
                    ordered.map { it.prescriptionOrdinal } == listOf(1, 2) &&
                    ordered.map { it.prescriptionLabel } == listOf("Progression", "Foundation")
            }
            val finalFamily = repository.getWorkoutStore().workouts
                .filter { it.recurringSessionId == sessionId }
                .sortedBy { it.prescriptionOrdinal }
            assertEquals(listOf("Progression", "Foundation"), finalFamily.map { it.prescriptionLabel })
            assertEquals(listOf(1, 2), finalFamily.map { it.prescriptionOrdinal })
            assertEquals(planOrderById, finalFamily.associate { it.id to it.order })
            closeWorkoutSelection()
            composeRule.waitUntil(10_000) {
                composeRule.onAllNodes(hasText("Suggested next:", substring = true))
                    .fetchSemanticsNodes().isEmpty()
            }

            clickTag("prescription_${baseWorkoutId}")
            waitForText("Foundation · $testName")
            composeRule.onAllNodes(hasText("View prescriptions"), useUnmergedTree = true)
                .fetchSemanticsNodes().size.let { assertEquals(0, it) }
            device.pressBack()
            waitForTag("session_prescriptions_${sessionId}")
            clickTag("session_back_to_workouts")
            waitForWorkoutsList(sessionId)

            openPlanSettings(testPlanId)
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").assertIsOff()
            composeRule.onNodeWithTag("suggest_next_prescription_toggle").performClick()
            clickText(device, "Save")
            waitForStore(repository) {
                it.workoutPlans.firstOrNull { plan -> plan.id == testPlanId }?.suggestNextPrescription == true
            }
            device.pressBack()
            composeRule.waitUntil(10_000) { hasComposeText("Workouts") }
            assertWorkoutsHasNoPlanSettingsAction()
            waitForWorkoutsList(sessionId)
            clickTag("recurring_session_${sessionId}")
            waitForTag("session_prescriptions_${sessionId}")
            waitForText("Suggested next: Progression", substring = true).performClick()
            waitForText("Progression · $testName")
        } finally {
            runCatching {
                device.takeScreenshot(File(context.cacheDir, "recurring_controls_final_state.png"))
                device.dumpWindowHierarchy(File(context.cacheDir, "recurring_controls_final_state.xml"))
            }
            scenario?.close()
            val latest = repository.getWorkoutStore()
            val testSessionIds = latest.workouts.filter { it.id == baseWorkoutId || it.id == secondWorkoutId }
                .mapNotNull { it.recurringSessionId }.toSet()
            repository.saveWorkoutStore(latest.copy(
                workouts = latest.workouts.filterNot {
                    it.id == baseWorkoutId || it.id == secondWorkoutId || it.recurringSessionId in testSessionIds
                },
                equipments = addedEquipmentId?.let { id ->
                    latest.equipments.filterNot { it.id == id }
                } ?: latest.equipments,
                workoutPlans = latest.workoutPlans.filterNot { it.id == testPlanId },
            ))
            Profiles.setLocallyChosenProfile(context, originalProfileId)
            Profiles.delete(context, profileId)
        }
    }

    private fun setTaggedEditText(tag: String, index: Int, value: String, failureContext: String = "") {
        try {
            composeRule.waitUntil(10_000) {
                composeRule.onAllNodes(hasTestTag(tag), useUnmergedTree = true)
                    .fetchSemanticsNodes().size > index
            }
        } catch (timeout: ComposeTimeoutException) {
            val context = ApplicationProvider.getApplicationContext<Context>()
            val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
            val screenshot = File(context.cacheDir, "recurring_controls_tag_timeout.png")
            val hierarchy = File(context.cacheDir, "recurring_controls_tag_timeout.xml")
            device.takeScreenshot(screenshot)
            device.dumpWindowHierarchy(hierarchy)
            val markerNames = listOf(
                "Manage recurring session", "Session name", "Prescription label",
                "Prescription number", "Save prescription", "Detach; keep workout history"
            )
            val markers = markerNames.associateWith { label ->
                composeRule.onAllNodes(hasText(label), useUnmergedTree = true).fetchSemanticsNodes().size
            }
            val fieldCount = composeRule.onAllNodes(hasTestTag(tag), useUnmergedTree = true)
                .fetchSemanticsNodes().size
            throw AssertionError(
                "Timed out locating tag=$tag index=$index; matchingCount=$fieldCount; " +
                    "managerMarkers=$markers; family=$failureContext; " +
                    "screenshot=${screenshot.absolutePath}; hierarchy=${hierarchy.absolutePath}",
                timeout,
            )
        }
        val field = composeRule.onAllNodes(hasTestTag(tag), useUnmergedTree = true)[index]
        field.performScrollTo()
        field.performClick()
        field.performTextClearance()
        field.performTextInput(value)
        field.assertTextEquals(value)
    }

    private fun dismissKeyboardIfVisible(device: UiDevice) {
        val keyboardVisible = InstrumentationRegistry.getInstrumentation()
            .uiAutomation.windows.any { it.type == AccessibilityWindowInfo.TYPE_INPUT_METHOD }
        if (keyboardVisible) {
            device.pressBack()
            device.waitForIdle()
        }
    }

    private fun assertExerciseEditorClosed(device: UiDevice) {
        composeRule.waitUntil(10_000) { !hasComposeText("Edit exercise") }
        waitForDescription("More")
    }

    private fun clickTagged(tag: String, index: Int) {
        composeRule.waitUntil(10_000) {
            composeRule.onAllNodes(hasTestTag(tag), useUnmergedTree = true)
                .fetchSemanticsNodes().size > index
        }
        val button = composeRule.onAllNodes(hasTestTag(tag), useUnmergedTree = true)[index]
        button.performScrollTo()
        button.assertIsDisplayed()
        button.assertIsEnabled()
        button.performClick()
        composeRule.waitForIdle()
    }

    private fun assertRecurringManagerClosed() {
        composeRule.waitUntil(10_000) { !hasComposeText("Manage recurring session") }
    }

    private fun openPlanSettings(planId: UUID) {
        waitForDescription("Menu").performClick()
        clickTag("navigation_plans")
        waitForText("Plans")
        clickTag("edit_plan_${planId}")
        waitForText("Plan settings")
    }

    private fun assertWorkoutsHasNoPlanSettingsAction() {
        check(composeRule.onAllNodes(hasTestTag("edit_selected_plan_settings"), useUnmergedTree = true)
            .fetchSemanticsNodes().isEmpty()) {
            "Workouts still exposes the removed plan settings action."
        }
        check(composeRule.onAllNodes(hasText("Manage plan settings"), useUnmergedTree = true)
            .fetchSemanticsNodes().isEmpty()) {
            "Workouts still exposes the removed Manage plan settings action."
        }
    }

    private fun waitForWorkoutsList(sessionId: UUID) {
        waitForTag("recurring_session_${sessionId}")
    }

    private fun assertWorkoutsShowsSingleSession(sessionId: UUID, baseWorkoutId: UUID) {
        val sessionCards = composeRule.onAllNodes(hasTestTag("recurring_session_${sessionId}"), useUnmergedTree = true)
            .fetchSemanticsNodes()
        check(sessionCards.size == 1) {
            "Expected one recurring-session card for $sessionId, found ${sessionCards.size}."
        }
        val prescriptionRows = composeRule.onAllNodes(hasTestTag("prescription_${baseWorkoutId}"), useUnmergedTree = true)
            .fetchSemanticsNodes()
        check(prescriptionRows.isEmpty()) {
            "Root Workouts list should keep prescriptions nested inside their session card."
        }
        check(composeRule.onAllNodes(hasTestTag("manage_recurring_session"), useUnmergedTree = true)
            .fetchSemanticsNodes().isEmpty()) {
            "Root Workouts list should not expose prescription management actions."
        }
        check(composeRule.onAllNodes(hasTestTag("add_prescription"), useUnmergedTree = true)
            .fetchSemanticsNodes().isEmpty()) {
            "Root Workouts list should not expose add-prescription actions."
        }
    }

    private fun openSessionPrescriptionManager(sessionId: UUID, workoutId: UUID) {
        waitForTag("session_prescriptions_${sessionId}")
        waitForTag("prescription_${workoutId}")
        val prescription = composeRule.onNodeWithTag("prescription_${workoutId}", useUnmergedTree = true)
        prescription.assertIsDisplayed()
        prescription.performTouchInput { longClick() }
        clickTag("manage_recurring_session")
        waitForText("Manage recurring session")
    }

    private fun dragPrescriptionBefore(sourceWorkoutId: UUID, targetWorkoutId: UUID) {
        val source = waitForTag("prescription_${sourceWorkoutId}")
        val target = waitForTag("prescription_${targetWorkoutId}")
        source.assertIsDisplayed()
        target.assertIsDisplayed()
        val sourceBounds = source.fetchSemanticsNode().boundsInRoot
        val targetBounds = target.fetchSemanticsNode().boundsInRoot
        check(targetBounds.center.y < sourceBounds.center.y) {
            "Expected target prescription $targetWorkoutId above source $sourceWorkoutId; " +
                "target=${targetBounds.center}, source=${sourceBounds.center}"
        }
        source.performTouchInput {
            val start = center
            val end = androidx.compose.ui.geometry.Offset(
                x = start.x,
                y = start.y + targetBounds.center.y - sourceBounds.center.y,
            )
            down(start)
            moveTo(end, delayMillis = 100)
            up()
        }
        composeRule.waitForIdle()
    }

    private fun movePrescriptionUp(workoutId: UUID) {
        waitForTag("prescription_${workoutId}")
            .performTouchInput { longClick() }
        composeRule.waitForIdle()
        val moveUp = waitForDescription("Move Up")
        moveUp.assertIsEnabled()
        moveUp.performClick()
        composeRule.waitForIdle()
    }

    private fun closeWorkoutSelection() {
        waitForDescription("Close").performClick()
        composeRule.waitForIdle()
    }

    private fun openRootSessionManager(sessionId: UUID) {
        val sessionCardTag = "recurring_session_${sessionId}"
        waitForTag(sessionCardTag)
        val sessionCard = composeRule.onNodeWithTag(sessionCardTag, useUnmergedTree = true)
        sessionCard.assertIsDisplayed()
        sessionCard.performTouchInput { longClick() }
        clickTag("manage_recurring_session")
        waitForText("Manage recurring session")
    }

    private fun clickText(device: UiDevice, text: String) {
        waitForText(text).performClick()
        composeRule.waitForIdle()
    }

    private fun waitForWorkoutsScreen(context: Context, device: UiDevice, driver: PhoneAppDriver) {
        val deadline = System.currentTimeMillis() + 45_000
        while (System.currentTimeMillis() < deadline) {
            if (hasComposeText("Workouts")) {
                clickTextAction(device, "Workouts")
                composeRule.waitForIdle()
                return
            }
            driver.dismissStartupPermissionDialogs(timeoutMs = 1_000)
            driver.grantHealthConnectPermissionsForE2E(timeoutMs = 2_000)
            device.waitForIdle(300)
        }
        val hierarchy = File(context.cacheDir, "recurring_controls_startup_timeout.xml")
        val screenshot = File(context.cacheDir, "recurring_controls_startup_timeout.png")
        device.dumpWindowHierarchy(hierarchy)
        device.takeScreenshot(screenshot)
        error(
            "Workouts tab did not appear after startup prompts. " +
                "Top package=" + device.currentPackageName +
                ", hierarchy=" + hierarchy.absolutePath +
                ", screenshot=" + screenshot.absolutePath
        )
    }

    private fun clickTextAction(device: UiDevice, text: String): Boolean {
        val matches = composeRule.onAllNodes(hasText(text)).fetchSemanticsNodes()
        if (matches.isEmpty()) return false
        composeRule.onAllNodes(hasText(text))[0].performClick()
        composeRule.waitForIdle()
        return true
    }

    private fun clickTag(tag: String, scroll: Boolean = false) {
        val node = waitForTag(tag)
        if (scroll) node.performScrollTo()
        node.performClick()
    }

    private fun clickPopupText(text: String) {
        waitForMatcher(hasText(text), useUnmergedTree = true).performClick()
    }

    private fun waitForTag(tag: String) = waitForMatcher(hasTestTag(tag), useUnmergedTree = true)

    private fun waitForText(
        text: String,
        substring: Boolean = false,
        scroll: Boolean = false,
    ): androidx.compose.ui.test.SemanticsNodeInteraction {
        val matcher = hasText(text, substring)
        waitForTextPresence(text, substring)
        return composeRule.onNode(matcher).also { if (scroll) it.performScrollTo() }
    }

    private fun waitForTextPresence(text: String, substring: Boolean = false) {
        composeRule.waitUntil(10_000) {
            composeRule.onAllNodes(hasText(text, substring), useUnmergedTree = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun waitForDescription(text: String, scroll: Boolean = false) =
        waitForMatcher(hasContentDescription(text))
            .also { if (scroll) it.performScrollTo() }

    private fun waitForDescriptionContains(text: String, scroll: Boolean = false): String {
        val node = waitForMatcher(hasContentDescription(text, substring = true))
        if (scroll) node.performScrollTo()
        return node.fetchSemanticsNode().config[androidx.compose.ui.semantics.SemanticsProperties.ContentDescription]
            .joinToString()
    }

    private fun hasComposeText(text: String) = runCatching {
        composeRule.onAllNodes(hasText(text), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
    }.getOrDefault(false)

    private fun waitForMatcher(
        matcher: androidx.compose.ui.test.SemanticsMatcher,
        useUnmergedTree: Boolean = false,
    ): androidx.compose.ui.test.SemanticsNodeInteraction {
        var matches = emptyList<androidx.compose.ui.semantics.SemanticsNode>()
        composeRule.waitUntil(10_000) {
            matches = composeRule.onAllNodes(matcher, useUnmergedTree).fetchSemanticsNodes()
            matches.isNotEmpty()
        }
        check(matches.size == 1) {
            "Expected one matching Compose node, found ${matches.size}: " +
                matches.joinToString { "${it.boundsInRoot} ${it.config}" }
        }
        return composeRule.onNode(matcher, useUnmergedTree)
    }

    private fun waitForStore(
        repository: WorkoutStoreRepository,
        condition: (com.gabstra.myworkoutassistant.shared.WorkoutStore) -> Boolean,
    ) {
        val deadline = System.currentTimeMillis() + 10_000
        var latest = repository.getWorkoutStore()
        while (System.currentTimeMillis() < deadline) {
            latest = repository.getWorkoutStore()
            if (condition(latest)) return
            Thread.sleep(100)
        }
        val recurringState = latest.workouts.filter { it.recurringSessionId != null }.joinToString { workout ->
            val exerciseState = workout.workoutComponents.filterIsInstance<Exercise>().joinToString { exercise ->
                "track=" + exercise.recurringExerciseId + ", policy=" + exercise.loadHistoryPolicy
            }
            "workout=" + workout.id + ", ordinal=" + workout.prescriptionOrdinal +
                ", label=" + workout.prescriptionLabel + ", " + exerciseState
        }
        assertTrue(
            "Timed out waiting for workout data to persist. Recurring state: " + recurringState,
            condition(latest),
        )
    }

    private fun exerciseByName(workout: Workout, name: String): Exercise =
        requireNotNull(exerciseByNameOrNull(workout, name)) {
            "Expected one fixture exercise named '$name' in workout ${workout.id}; " +
                "found=${workout.workoutComponents.filterIsInstance<Exercise>().map { it.id to it.name }}"
        }

    private fun exerciseByNameOrNull(workout: Workout, name: String): Exercise? {
        val matches = workout.workoutComponents.filterIsInstance<Exercise>().filter { it.name == name }
        check(matches.size <= 1) {
            "Expected at most one fixture exercise named '$name' in workout ${workout.id}; " +
                "found=${matches.map { it.id }}"
        }
        return matches.firstOrNull()
    }

    private fun exerciseTrackSignature(workouts: List<Workout>, sessionId: UUID, exerciseName: String): String =
        workouts.filter { it.recurringSessionId == sessionId }.joinToString { workout ->
            val exercise = exerciseByName(workout, exerciseName)
            "${workout.id}: name=${workout.name}, exercise=${exercise.id}/${exercise.name}, " +
                "type=${exercise.exerciseType}, equipment=${exercise.equipmentId}, " +
                "definition=${exercise.exerciseDefinitionId}, track=${exercise.recurringExerciseId}"
        }
}
