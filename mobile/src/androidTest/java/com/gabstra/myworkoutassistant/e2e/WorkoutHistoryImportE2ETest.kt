package com.gabstra.myworkoutassistant.e2e

import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.os.Environment
import android.provider.MediaStore
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.core.app.ActivityScenario
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.MainActivity
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.history.importing.WorkoutHistoryImportPackage
import com.gabstra.myworkoutassistant.shared.workout.history.importing.WorkoutHistoryImportService
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.io.File
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkoutHistoryImportE2ETest {
    @get:Rule
    val composeRule = createEmptyComposeRule()

    @Test
    fun importHistoryThroughWorkoutPicker_appendsAndReplaysWithoutReplacingExistingRows() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val originalProfileId = Profiles.activeProfileId(context)
        val profileIndexFile = File(context.filesDir, "profiles/index.json")
        val originalProfileIndex = profileIndexFile.takeIf { it.exists() }?.readBytes()
        val profileSyncPreferences = context.getSharedPreferences("profile_sync", Context.MODE_PRIVATE)
        val hadLocalChoice = profileSyncPreferences.contains("local_choice_made")
        val originalLocalChoice = profileSyncPreferences.getBoolean("local_choice_made", false)
        val sharedStoreArtifacts = listOf(
            context.getFileStreamPath("workout_store.json"),
            context.getFileStreamPath("workout_store.json.v1-recovery"),
            context.getFileStreamPath("workout_store.json.tmp"),
        ).associateWith { file -> file.takeIf { it.exists() }?.readBytes() }
        val scratchProfile = Profiles.create(context, "History import E2E ${UUID.randomUUID().toString().take(8)}")
        val fileName = "mwa-history-import-${UUID.randomUUID()}.json"
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        var stagedFile: android.net.Uri? = null
        var database: AppDatabase? = null
        var scenario: ActivityScenario<MainActivity>? = null
        try {
            check(Profiles.setLocallyChosenProfile(context, scratchProfile.id))
            val fixture = CrossDeviceSyncPhoneWorkoutStoreFixture.createWorkoutStore()
            val sourceWorkout = fixture.workouts.first()
            val sourceExercise = sourceWorkout.workoutComponents.filterIsInstance<Exercise>().first()
            val sourceSet = sourceExercise.sets.filterIsInstance<WeightSet>()
                .first { it.subCategory == SetSubCategory.WorkSet }
            val recurringSessionId = UUID.randomUUID()
            val trackId = UUID.randomUUID()
            val importedPrescriptionSetId = UUID.randomUUID()
            val exercise = sourceExercise.copy(
                id = UUID.randomUUID(),
                name = "Imported history fixture exercise",
                movementRef = null,
                exerciseDefinitionId = null,
                recurringExerciseId = trackId,
                sets = sourceExercise.sets.map { set ->
                    if (set.id == sourceSet.id) (set as WeightSet).copy(id = importedPrescriptionSetId) else set
                },
            )
            val workout = sourceWorkout.copy(
                id = UUID.randomUUID(),
                name = "Imported history fixture workout",
                workoutComponents = listOf(exercise),
                order = 1,
                creationDate = LocalDate.now(),
                globalId = UUID.randomUUID(),
                workoutPlanId = null,
                recurringSessionId = recurringSessionId,
                prescriptionOrdinal = 1,
                prescriptionLabel = "Week 1 A",
                previousVersionId = null,
                nextVersionId = null,
            )
            val store = fixture.copy(workouts = listOf(workout), workoutPlans = emptyList())
            val repository = WorkoutStoreRepository(
                Profiles.directory(context, scratchProfile.id),
                context.filesDir,
            )
            repository.saveWorkoutStore(store)

            // The production JSON adapter assigns canonical exercise-definition IDs on read.
            // Build imported occurrence snapshots from that same persisted representation.
            val persistedStore = repository.getWorkoutStore()
            val persistedWorkout = requireNotNull(persistedStore.workouts.singleOrNull { it.id == workout.id })
            val persistedExercise = persistedWorkout.workoutComponents.filterIsInstance<Exercise>()
                .single { it.id == exercise.id }
            assertNotNull("Persisted fixture exercise should have its canonical definition ID.", persistedExercise.exerciseDefinitionId)
            val importedPrescriptionSet = persistedExercise.sets.filterIsInstance<WeightSet>()
                .single { it.id == importedPrescriptionSetId }
            val performedEquipmentId = persistedExercise.equipmentId
            val performedWeightEquipment = performedEquipmentId?.let { equipmentId ->
                persistedStore.equipments.firstOrNull { it.id == equipmentId }
            }
            val performedAccessoryEquipment = performedEquipmentId?.let { equipmentId ->
                persistedStore.accessoryEquipments.firstOrNull { it.id == equipmentId }
            }

            database = AppDatabase.getDatabase(context, scratchProfile.id)
            val priorHistory = WorkoutHistory(
                id = UUID.randomUUID(),
                workoutId = workout.id,
                date = LocalDate.of(2026, 11, 1),
                time = LocalTime.of(8, 0),
                startTime = LocalDateTime.of(2026, 11, 1, 8, 0),
                duration = 600,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workout.globalId,
                recurringSessionId = recurringSessionId,
            )
            runBlocking {
                database!!.workoutHistoryDao().insert(priorHistory)
            }

            val importedHistory = WorkoutHistory(
                id = UUID.randomUUID(),
                workoutId = workout.id,
                date = LocalDate.of(2026, 11, 8),
                time = LocalTime.MIDNIGHT,
                startTime = LocalDateTime.of(2026, 11, 8, 0, 0),
                duration = 0,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = workout.globalId,
                recurringSessionId = recurringSessionId,
                origin = WorkoutHistoryOrigin.USER_IMPORTED,
                startTimeKnown = false,
                durationKnown = false,
            )
            val importedSet = SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = importedHistory.id,
                exerciseId = persistedExercise.id,
                equipmentIdSnapshot = persistedExercise.equipmentId,
                equipmentNameSnapshot = performedWeightEquipment?.name ?: performedAccessoryEquipment?.name,
                equipmentTypeSnapshot = performedWeightEquipment?.type?.name ?: performedAccessoryEquipment?.type?.name,
                setId = importedPrescriptionSet.id,
                order = 0u,
                startTime = null,
                endTime = null,
                setData = WeightSetData(
                    actualReps = 8,
                    actualWeight = 37.5,
                    volume = 300.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
                skipped = false,
                recurringExerciseId = persistedExercise.recurringExerciseId,
                exerciseDefinitionIdSnapshot = persistedExercise.exerciseDefinitionId,
                exerciseTypeSnapshot = persistedExercise.exerciseType.name,
            )
            val payload = WorkoutHistoryImportPackage(
                profileId = scratchProfile.id,
                workoutHistories = listOf(importedHistory),
                setHistories = listOf(importedSet),
            )
            WorkoutHistoryImportService.validate(persistedStore, scratchProfile.id, payload)
            val serializedPayload = payload.toJson()
            stagedFile = stageHistoryPackage(context, fileName, serializedPayload)
            assertStagedDownload(context, requireNotNull(stagedFile), fileName, serializedPayload)

            scenario = ActivityScenario.launch(
                Intent(context, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK)
            )
            val driver = PhoneAppDriver(device, context)
            waitForMenuAfterStartup(device, driver)
            openHistoryImportFromMenu(device)
            selectDownload(device, fileName)

            waitForHistoryReview(device, scratchProfile.name)
            waitForText("Import history")
            waitForText(scratchProfile.name)
            waitForText("1 sessions · 1 sets")
            val localizedDate = LocalDate.of(2026, 11, 8).format(
                DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM).withLocale(Locale.getDefault())
            )
            waitForText(localizedDate)
            assertTextAbsent("${scratchProfile.id}")
            assertTextAbsent("unknown")
            assertTextAbsent("Source notes")
            assertEquals(1, runBlocking { database!!.workoutHistoryDao().getAllWorkoutHistories().size })

            clickText("Import history")
            waitForRows(database, scratchProfile.id, expectedHistoryCount = 2, expectedSetCount = 1)
            waitForHistoryReviewClosed()
            val afterFirstImport = runBlocking {
                database!!.workoutHistoryDao().getAllWorkoutHistories()
                    .sortedBy { it.date }
            }
            assertEquals(listOf(priorHistory.id, importedHistory.id), afterFirstImport.map { it.id })
            assertEquals(priorHistory, afterFirstImport.first())
            assertEquals(WorkoutHistoryOrigin.USER_IMPORTED, afterFirstImport.last().origin)
            assertEquals(37.5, (runBlocking {
                database!!.setHistoryDao().getSetHistoriesByWorkoutHistoryId(importedHistory.id).single().setData
            } as WeightSetData).actualWeight, 0.0)
            assertEquals(scratchProfile.id, Profiles.activeProfileId(context))

            openHistoryImportFromMenu(device)
            selectDownload(device, fileName)
            waitForHistoryReview(device, scratchProfile.name)
            waitForText("Import history")
            waitForText(scratchProfile.name)
            assertTextAbsent("${scratchProfile.id}")
            clickText("Import history")
            waitForHistoryReviewClosed()
            composeRule.waitUntil(15_000) {
                runBlocking { database!!.workoutHistoryDao().getAllWorkoutHistories().size == 2 }
            }
            assertEquals(1, runBlocking {
                database!!.setHistoryDao().getSetHistoriesByWorkoutHistoryId(importedHistory.id).size
            })
        } finally {
            runCatching {
                device.takeScreenshot(File(context.cacheDir, "history-import-final-state.png"))
                device.dumpWindowHierarchy(File(context.cacheDir, "history-import-final-state.xml"))
            }
            runCatching {
                val captureStem = "history-import-${fileName.removeSuffix(".json")}"
                device.takeScreenshot(File(context.cacheDir, "$captureStem.png"))
                device.dumpWindowHierarchy(File(context.cacheDir, "$captureStem.xml"))
            }
            runCatching { scenario?.close() }
            Profiles.setActiveProfile(context, originalProfileId)
            profileSyncPreferences.edit().apply {
                if (hadLocalChoice) putBoolean("local_choice_made", originalLocalChoice)
                else remove("local_choice_made")
            }.commit()
            database?.close()
            if (Profiles.profiles(context).any { it.id == scratchProfile.id }) {
                Profiles.delete(context, scratchProfile.id)
            }
            if (originalProfileIndex == null) {
                profileIndexFile.delete()
            } else {
                profileIndexFile.writeBytes(originalProfileIndex)
            }
            stagedFile?.let { runCatching { context.contentResolver.delete(it, null, null) } }
            sharedStoreArtifacts.forEach { (file, originalBytes) ->
                if (originalBytes == null) {
                    file.delete()
                } else {
                    file.writeBytes(originalBytes)
                }
            }
        }
    }

    private fun stageHistoryPackage(context: Context, name: String, json: String): android.net.Uri {
        val resolver = context.contentResolver
        val jsonBytes = json.toByteArray(Charsets.UTF_8)
        val uri = requireNotNull(resolver.insert(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, name)
                put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
                put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
                if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                    put(MediaStore.MediaColumns.IS_PENDING, 1)
                }
            },
        )) { "Could not stage an isolated history import file." }
        try {
            requireNotNull(resolver.openOutputStream(uri)) {
                "Could not write the isolated history import file."
            }.use { output ->
                output.write(jsonBytes)
                output.flush()
            }
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                resolver.update(
                    uri,
                    ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                    null,
                    null,
                )
            }
            return uri
        } catch (error: Throwable) {
            resolver.delete(uri, null, null)
            throw error
        }
    }

    private fun assertStagedDownload(
        context: Context,
        uri: android.net.Uri,
        expectedName: String,
        expectedJson: String,
    ) {
        val projection = buildList {
            add(MediaStore.MediaColumns.DISPLAY_NAME)
            add(MediaStore.MediaColumns.SIZE)
            add(MediaStore.MediaColumns.RELATIVE_PATH)
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                add(MediaStore.MediaColumns.IS_PENDING)
            }
        }.toTypedArray()
        val row = requireNotNull(context.contentResolver.query(uri, projection, null, null, null)) {
            "The staged download could not be queried."
        }.use { cursor ->
            check(cursor.moveToFirst()) { "The staged download row was not published." }
            val name = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.DISPLAY_NAME))
            val size = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.SIZE))
            val relativePath = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.RELATIVE_PATH))
            val isPending = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.Q) {
                cursor.getInt(cursor.getColumnIndexOrThrow(MediaStore.MediaColumns.IS_PENDING))
            } else {
                0
            }
            Triple(name, size, relativePath to isPending)
        }
        val expectedBytes = expectedJson.toByteArray(Charsets.UTF_8)
        val readBack = requireNotNull(context.contentResolver.openInputStream(uri)) {
            "The staged download could not be read back."
        }.use { it.readBytes() }
        assertEquals("Staged filename", expectedName, row.first)
        assertEquals("Staged file size", expectedBytes.size.toLong(), row.second)
        assertTrue(
            "The staged download should be inside Downloads.",
            row.third.first == "${Environment.DIRECTORY_DOWNLOADS}/",
        )
        assertEquals("The staged file must be published before opening the picker.", 0, row.third.second)
        assertTrue("Staged bytes differ from the serialized import package.", readBack.contentEquals(expectedBytes))
    }

    private fun openHistoryImportFromMenu(device: UiDevice) {
        clickDescription("Menu")
        clickText("Data")
        clickText("Import plan or history")
        check(device.wait(Until.hasObject(By.pkg("com.google.android.documentsui")), 10_000)) {
            "The system document picker did not open."
        }
    }

    private fun clickDescription(description: String) {
        composeRule.waitUntil(15_000) {
            composeRule.onAllNodes(hasContentDescription(description), useUnmergedTree = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
        composeRule.onNode(hasContentDescription(description), useUnmergedTree = true).performClick()
        composeRule.waitForIdle()
    }

    private fun waitForMenuAfterStartup(device: UiDevice, driver: PhoneAppDriver) {
        val deadline = System.currentTimeMillis() + 45_000
        while (System.currentTimeMillis() < deadline) {
            composeRule.waitForIdle()
            if (hasComposeText("Workouts") && device.hasObject(By.desc("Menu"))) return
            driver.dismissStartupPermissionDialogs(timeoutMs = 1_000)
            driver.grantHealthConnectPermissionsForE2E(timeoutMs = 2_000)
            device.waitForIdle(300)
        }
        val context = ApplicationProvider.getApplicationContext<Context>()
        val screenshot = File(context.cacheDir, "history-import-startup-timeout.png")
        val hierarchy = File(context.cacheDir, "history-import-startup-timeout.xml")
        device.takeScreenshot(screenshot)
        device.dumpWindowHierarchy(hierarchy)
        error(
            "Workout menu did not appear after startup prompts; foreground=${device.currentPackageName}; " +
                "hierarchy=${hierarchy.readText()}; screenshot=${screenshot.absolutePath}"
        )
    }

    private fun hasComposeText(text: String): Boolean = composeRule.run {
        onAllNodes(hasText(text), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
    }

    private fun selectDownload(device: UiDevice, fileName: String) {
        try {
            clickFreshPickerObject(device, By.desc("Show roots"), "Show roots", timeoutMs = 5_000)
            capturePickerState(device, fileName, "roots")
            clickFreshPickerObject(device, By.text("Downloads"), "Downloads", timeoutMs = 5_000)
            device.waitForIdle()
            val downloadsTitle = device.wait(Until.findObject(By.text("Downloads")), 2_000)
            val recentTitle = device.findObject(By.text("Recent"))
            if (downloadsTitle == null || recentTitle != null) {
                val (screenshot, hierarchy) = capturePickerState(device, fileName, "wrong-location")
                error(
                    "Picker did not select Downloads for '$fileName'; screenshot=${screenshot.absolutePath}; " +
                        "hierarchy=${hierarchy.absolutePath}"
                )
            }
            capturePickerState(device, fileName, "downloads")
            clickFreshPickerObject(device, By.text(fileName), fileName, timeoutMs = 15_000)
            val openButton = device.wait(Until.findObject(By.text("Open")), 2_000)
            if (openButton != null) {
                clickFreshPickerObject(device, By.text("Open"), "Open", timeoutMs = 5_000)
            }
        } catch (error: Throwable) {
            val (screenshot, hierarchy) = capturePickerState(device, fileName, "current")
            throw AssertionError(
                "Picker failed for staged file '$fileName'; screenshot=${screenshot.absolutePath}; " +
                    "hierarchy=${hierarchy.absolutePath}",
                error,
            )
        }
    }

    private fun capturePickerState(
        device: UiDevice,
        fileName: String,
        stage: String,
    ): Pair<File, File> {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val captureStem = "history-import-${fileName.removeSuffix(".json")}-$stage"
        val screenshot = File(context.cacheDir, "$captureStem.png")
        val hierarchy = File(context.cacheDir, "$captureStem.xml")
        runCatching {
            device.takeScreenshot(screenshot)
            device.dumpWindowHierarchy(hierarchy)
        }
        return screenshot to hierarchy
    }

    private fun clickFreshPickerObject(
        device: UiDevice,
        selector: BySelector,
        description: String,
        timeoutMs: Long,
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastStale: StaleObjectException? = null
        while (System.currentTimeMillis() < deadline) {
            val remaining = (deadline - System.currentTimeMillis()).coerceAtLeast(1L)
            val target = device.wait(Until.findObject(selector), minOf(1_000L, remaining)) ?: continue
            try {
                target.click()
                device.waitForIdle()
                return
            } catch (error: StaleObjectException) {
                lastStale = error
            }
        }
        if (lastStale != null) throw lastStale
        error("The document picker item '$description' did not appear in time.")
    }

    private fun waitForText(text: String, substring: Boolean = false) = composeRule.run {
        waitUntil(15_000) {
            onAllNodes(hasText(text, substring = substring), useUnmergedTree = true)
                .fetchSemanticsNodes().isNotEmpty()
        }
        assertTrue(
            "Expected visible text '$text'.",
            onAllNodes(hasText(text, substring = substring), useUnmergedTree = true)
                .fetchSemanticsNodes().isNotEmpty(),
        )
    }

    private fun clickText(text: String) {
        waitForText(text)
        composeRule.onNodeWithText(text, useUnmergedTree = true).performClick()
        composeRule.waitForIdle()
    }

    private fun assertTextAbsent(text: String) {
        assertTrue(
            "Unexpected visible text '$text'.",
            composeRule.onAllNodes(hasText(text, substring = true), useUnmergedTree = true)
                .fetchSemanticsNodes().isEmpty(),
        )
    }

    private fun waitForHistoryReviewClosed() {
        composeRule.waitUntil(15_000) {
            composeRule.onAllNodes(hasText("Import history"), useUnmergedTree = true)
                .fetchSemanticsNodes().isEmpty()
        }
    }

    private fun waitForHistoryReview(device: UiDevice, profileName: String) {
        val deadline = System.currentTimeMillis() + 15_000
        while (System.currentTimeMillis() < deadline) {
            if (hasComposeText("Import history") && hasComposeText(profileName)) return
            val validationToast = device.findObject(
                By.textContains("Couldn't review that workout history.")
            )
            if (validationToast != null) {
                error("History import was rejected before review: ${validationToast.text}")
            }
            composeRule.waitForIdle()
            device.waitForIdle(100)
        }
        val context = ApplicationProvider.getApplicationContext<Context>()
        val screenshot = File(context.cacheDir, "history-import-review-missing.png")
        val hierarchy = File(context.cacheDir, "history-import-review-missing.xml")
        device.takeScreenshot(screenshot)
        device.dumpWindowHierarchy(hierarchy)
        error(
            "History review dialog did not appear after document selection; " +
                "foreground=${device.currentPackageName}; hierarchy=${hierarchy.readText()}; " +
                "screenshot=${screenshot.absolutePath}"
        )
    }

    private fun waitForRows(
        database: AppDatabase,
        profileId: String,
        expectedHistoryCount: Int,
        expectedSetCount: Int,
    ) {
        composeRule.waitUntil(15_000) {
            runBlocking {
                database.workoutHistoryDao().getAllWorkoutHistories().size == expectedHistoryCount &&
                    database.setHistoryDao().getAllSetHistories().size == expectedSetCount
            }
        }
        assertEquals(expectedHistoryCount, runBlocking { database.workoutHistoryDao().getAllWorkoutHistories().size })
        assertEquals(profileId, Profiles.activeProfileId(ApplicationProvider.getApplicationContext()))
    }
}
