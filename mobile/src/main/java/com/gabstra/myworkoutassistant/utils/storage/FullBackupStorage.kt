package com.gabstra.myworkoutassistant

import android.content.Context
import android.util.Base64
import android.util.Log
import com.gabstra.myworkoutassistant.insights.RemoteOpenAiConfig
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsMode
import com.gabstra.myworkoutassistant.insights.WorkoutInsightsSettingsStore
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.FullBackup
import com.gabstra.myworkoutassistant.shared.FullBackupSettings
import com.gabstra.myworkoutassistant.shared.MotionCaptureFileBackup
import com.gabstra.myworkoutassistant.shared.ProfileBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutStore
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.mergedWithPersonalSettingsOf
import com.gabstra.myworkoutassistant.shared.motion.collectExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.shared.personalSettingsOnly
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.gabstra.myworkoutassistant.shared.sharedContentOnly
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

private const val TAG = "FullBackup"

/** Recording payloads dominate the file, so cap what one backup may carry. */
private const val MAX_MOTION_CAPTURE_BYTES = 256L * 1024 * 1024

private const val SHARED_STORE_FILE = "workout_store.json"
private const val MOTION_CAPTURE_ROOT = "motion_capture"

/**
 * Builds a backup of the whole install: the shared content once, every profile with its own
 * personal settings and history, shared movement payloads, device-wide settings and sensor
 * recordings.
 *
 * Returns null when there is nothing to export yet.
 */
suspend fun createFullBackup(context: Context): FullBackup? = withContext(Dispatchers.IO) {
    val profiles = Profiles.profiles(context)
    if (profiles.isEmpty()) return@withContext null
    val sharedStore = readSharedStore(context) ?: return@withContext null

    val profileBackups = profiles.mapNotNull { profile ->
        val merged = WorkoutStoreRepository(
            Profiles.directory(context, profile.id),
            context.filesDir,
        ).getWorkoutStore()
        val db = AppDatabase.getDatabase(context, profile.id)
        val backup = createAppBackup(merged, db, context) ?: emptyBackupFor(merged)
        ProfileBackup(
            profileId = profile.id,
            profileName = profile.name,
            // Only the personal half: the shared content is stored once on the envelope, and
            // device-wide settings are collected separately.
            backup = backup.copy(
                WorkoutStore = backup.WorkoutStore.personalSettingsOnly(),
                ExerciseMovements = null,
                MobileLlmEnabled = null,
                WorkoutInsightsMode = null,
                RemoteInsightsBaseUrl = null,
                RemoteInsightsApiKey = null,
                RemoteInsightsModel = null,
                WorkoutInsightsCustomInstructions = null,
            ),
        )
    }

    val movements = runCatching { collectExerciseMovementBackups(context, sharedStore) }
        .onFailure { Log.w(TAG, "Continuing without exercise movement payloads", it) }
        .getOrDefault(emptyList())

    FullBackup(
        createdAtEpochMs = System.currentTimeMillis(),
        sharedStore = sharedStore,
        activeProfileId = Profiles.activeProfileId(context),
        profiles = profileBackups,
        exerciseMovements = movements,
        settings = collectFullBackupSettings(context),
        motionCaptureFiles = collectMotionCaptureFiles(context),
    )
}

fun readSharedStore(context: Context): com.gabstra.myworkoutassistant.shared.WorkoutStore? {
    val file = File(context.filesDir, SHARED_STORE_FILE)
    if (!file.exists()) return null
    return runCatching { fromJSONToWorkoutStore(file.readText()).sharedContentOnly() }
        .onFailure { Log.w(TAG, "Could not read the shared store", it) }
        .getOrNull()
}

fun writeSharedStore(context: Context, sharedStore: com.gabstra.myworkoutassistant.shared.WorkoutStore) {
    val file = File(context.filesDir, SHARED_STORE_FILE)
    val temporary = File(file.parentFile, "${file.name}.tmp")
    temporary.writeText(fromWorkoutStoreToJSON(sharedStore.sharedContentOnly()))
    if (!temporary.renameTo(file)) {
        file.delete()
        temporary.renameTo(file)
    }
}

fun restoreFullBackupPayloads(
    context: Context,
    fullBackup: FullBackup,
) {
    restoreExerciseMovementBackups(context, fullBackup.exerciseMovements)
    restoreMotionCaptureFiles(context, fullBackup.motionCaptureFiles)
}

fun restoreFullBackupSettings(context: Context, settings: FullBackupSettings?) {
    if (settings == null) return
    settings.mobileLlmEnabled?.let { WorkoutInsightsSettingsStore.setEnabled(context, it) }
    settings.workoutInsightsMode
        ?.let { WorkoutInsightsMode.fromStoredValue(it) }
        ?.let { WorkoutInsightsSettingsStore.setMode(context, it) }
    if (settings.remoteBaseUrl != null || settings.remoteApiKey != null || settings.remoteModel != null) {
        WorkoutInsightsSettingsStore.setRemoteConfig(
            context,
            RemoteOpenAiConfig(
                baseUrl = settings.remoteBaseUrl.orEmpty(),
                apiKey = settings.remoteApiKey.orEmpty(),
                model = settings.remoteModel.orEmpty(),
            ),
        )
    }
    settings.customInstructions?.let { WorkoutInsightsSettingsStore.setCustomInstructions(context, it) }
    settings.alertSoundEnabled?.let { AlertSoundPreferences.setEnabled(context, it) }
    settings.healthConnectProfileId?.let { Profiles.setHealthConnectProfile(context, it) }
}

private fun collectFullBackupSettings(context: Context): FullBackupSettings =
    FullBackupSettings(
        mobileLlmEnabled = WorkoutInsightsSettingsStore.isEnabled(context),
        workoutInsightsMode = WorkoutInsightsSettingsStore.getMode(context).name,
        remoteBaseUrl = WorkoutInsightsSettingsStore.getRemoteConfig(context).baseUrl,
        remoteApiKey = WorkoutInsightsSettingsStore.getRemoteConfig(context).apiKey,
        remoteModel = WorkoutInsightsSettingsStore.getRemoteConfig(context).model,
        customInstructions = WorkoutInsightsSettingsStore.getCustomInstructions(context),
        alertSoundEnabled = AlertSoundPreferences.isEnabled(context),
        healthConnectProfileId = Profiles.healthConnectProfileId(context),
    )

private fun emptyBackupFor(store: com.gabstra.myworkoutassistant.shared.WorkoutStore) = AppBackup(
    store,
    emptyList(),
    emptyList(),
    emptyList(),
    emptyList(),
    emptyList(),
    emptyList(),
)

private fun collectMotionCaptureFiles(context: Context): List<MotionCaptureFileBackup> {
    val root = File(context.filesDir, MOTION_CAPTURE_ROOT)
    if (!root.exists()) return emptyList()

    val files = root.walkTopDown().filter { it.isFile }.toList()
    var total = 0L
    val collected = mutableListOf<MotionCaptureFileBackup>()
    for (file in files) {
        if (total + file.length() > MAX_MOTION_CAPTURE_BYTES) {
            Log.w(TAG, "Motion capture budget reached; skipping ${file.name} and the rest")
            break
        }
        runCatching {
            val compressed = ByteArrayOutputStream().use { buffer ->
                GZIPOutputStream(buffer).use { it.write(file.readBytes()) }
                buffer.toByteArray()
            }
            total += file.length()
            collected += MotionCaptureFileBackup(
                relativePath = file.relativeTo(context.filesDir).invariantSeparatorsPath,
                gzipBase64 = Base64.encodeToString(compressed, Base64.NO_WRAP),
            )
        }.onFailure { Log.w(TAG, "Skipping motion capture file ${file.name}", it) }
    }
    return collected
}

private fun restoreMotionCaptureFiles(context: Context, files: List<MotionCaptureFileBackup>) {
    files.forEach { entry ->
        runCatching {
            val target = File(context.filesDir, entry.relativePath)
            if (!target.canonicalPath.startsWith(File(context.filesDir, MOTION_CAPTURE_ROOT).canonicalPath)) {
                Log.w(TAG, "Refusing to restore outside motion_capture: ${entry.relativePath}")
                return@runCatching
            }
            target.parentFile?.mkdirs()
            val compressed = Base64.decode(entry.gzipBase64, Base64.NO_WRAP)
            GZIPInputStream(compressed.inputStream()).use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
        }.onFailure { Log.w(TAG, "Could not restore ${entry.relativePath}", it) }
    }
}
