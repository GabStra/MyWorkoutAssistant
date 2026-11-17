package com.gabstra.myworkoutassistant.shared.profile

import android.content.Context
import android.content.SharedPreferences
import android.os.Handler
import android.os.Looper
import com.google.gson.Gson
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutStore
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.personalSettingsOnly
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import java.util.UUID

/**
 * Owns the profile list and the data roots derived from it.
 *
 * A profile is just a directory plus a database name, so every reader keeps its current
 * shape and only asks this object for the root it should use.
 */
object Profiles {
    private const val PROFILES_DIR = "profiles"
    private const val INDEX_FILE = "index.json"
    private const val INDEX_CORRUPT_SUFFIX = ".corrupt"
    private const val WORKOUT_STORE_FILE = "workout_store.json"

    const val DEFAULT_PROFILE_ID = "default"
    private const val DEFAULT_PROFILE_NAME = "Profile 1"

    /** The database name used before profiles existed; adopted by the default profile on first run. */
    private const val LEGACY_DATABASE_NAME = "app_database_2"
    private val SQLITE_SIDECARS = listOf("", "-wal", "-shm")

    private const val PROFILE_SYNC_PREFS = "profile_sync"
    private const val PROFILE_INDEX_REVISION_KEY = "profile_index_revision"
    private const val REMOTE_PROFILE_COUNT_KEY = "remote_profile_count"
    private const val REMOTE_ACTIVE_PROFILE_ID_KEY = "remote_active_profile_id"
    private const val LOCAL_CHOICE_KEY = "local_choice_made"
    private const val HEALTH_CONNECT_PROFILE_KEY = "health_connect_profile_id"

    private val gson = Gson()
    private val lock = Any()

    // The index is parsed once per process and revalidated against the file's identity, so
    // every database access can resolve the active profile without a read and parse.
    @Volatile
    private var cachedStamp: Long = Long.MIN_VALUE

    @Volatile
    private var cachedIndex: ProfileIndex? = null

    fun index(context: Context): ProfileIndex {
        val app = context.applicationContext
        val file = indexFile(app)
        val currentStamp = stamp(file)
        cachedIndex?.takeIf { cachedStamp == currentStamp }?.let { return it }
        return synchronized(lock) {
            cachedIndex?.takeIf { cachedStamp == currentStamp } ?: readIndex(app).also {
                cachedIndex = it
                cachedStamp = stamp(file)
            }
        }
    }

    fun profiles(context: Context): List<UserProfile> = index(context).profiles

    fun activeProfileId(context: Context): String = index(context).activeProfileId

    fun activeProfile(context: Context): UserProfile {
        val index = index(context)
        return index.profiles.firstOrNull { it.id == index.activeProfileId }
            ?: index.profiles.first()
    }

    fun directory(context: Context, profileId: String): File =
        File(File(context.applicationContext.filesDir, PROFILES_DIR), profileId)

    fun activeDirectory(context: Context): File =
        directory(context, activeProfileId(context)).apply { mkdirs() }

    fun databaseName(profileId: String): String = "app_database_$profileId"

    /**
     * Resolves the profile a payload names.
     *
     * A payload without the key predates profiles, so it belongs to the active profile. An id
     * that is present but unknown belongs to a profile deleted on this device, and must be
     * dropped — falling back to the active profile would file one person's data under another.
     */
    fun resolvePayloadProfile(context: Context, payloadProfileId: String?): String? {
        if (payloadProfileId == null) return activeProfileId(context)
        return payloadProfileId.takeIf { id -> index(context).profiles.any { it.id == id } }
    }

    /**
     * Resolves the destination for a phone-originated full backup. Legacy payloads without a
     * profile id retain the historical active-profile behavior. A named target is never
     * redirected to the active profile: unknown IDs are admitted only as canonical UUIDs with
     * a usable profile name, then added without changing this device's selection.
     */
    fun ensureIncomingBackupProfile(
        context: Context,
        payloadProfileId: String?,
        payloadProfileName: String?,
    ): String? {
        if (payloadProfileId == null) return activeProfileId(context)

        val normalizedName = payloadProfileName?.trim()
        if (payloadProfileName != null &&
            (normalizedName.isNullOrEmpty() || normalizedName.any { Character.isISOControl(it) })
        ) {
            return null
        }

        val existing = index(context).profiles.firstOrNull { it.id == payloadProfileId }
        if (existing != null) {
            directory(context, payloadProfileId).mkdirs()
            if (!normalizedName.isNullOrEmpty() && existing.name != normalizedName) {
                rename(context, payloadProfileId, normalizedName)
            }
            return payloadProfileId
        }

        val validUuid = runCatching { UUID.fromString(payloadProfileId).toString() == payloadProfileId }
            .getOrDefault(false)
        if (!validUuid || normalizedName.isNullOrEmpty()) return null

        ensureProfile(context, payloadProfileId, normalizedName)
        return payloadProfileId.takeIf { id -> index(context).profiles.any { it.id == id } }
    }

    /** Publishes the list and the current selection, e.g. to a paired watch. */
    fun exportIndexJson(context: Context): String = gson.toJson(index(context))

    /**
     * Updates the profile list from the paired phone without changing this device's selection.
     *
     * The phone's selection is only recorded here and adopted by [alignActiveProfileWithPhone]
     * on the next cold start: swapping the active profile while the app holds state would make
     * the next save attribute that state to the wrong person.
     */
    fun applyRemoteIndexJson(context: Context, json: String): Boolean {
        val remote = runCatching { gson.fromJson(json, ProfileIndex::class.java) }
            .getOrNull() ?: return false
        val profiles: List<UserProfile> = remote.profiles.filterNotNull()
        if (profiles.isEmpty()) return false
        val remoteActive = profiles.firstOrNull { it.id == remote.activeProfileId }?.id
            ?: profiles.first().id
        val localIndex = index(context)
        val currentActive = localIndex.activeProfileId
        // Keep this device's own selection: switching it here would rebind a running app
        // underneath state that still belongs to the previous profile. If the phone no longer
        // lists it, keep our cached entry so the index stays self-consistent.
        val missingLocalEntry = localIndex.profiles
            .firstOrNull { it.id == currentActive }
            ?.takeIf { local -> profiles.none { it.id == local.id } }
        writeIndex(
            context,
            ProfileIndex(
                activeProfileId = currentActive,
                profiles = profiles + listOfNotNull(missingLocalEntry),
            ),
        )
        remoteSelectionPrefs(context).edit()
            .putString(REMOTE_ACTIVE_PROFILE_ID_KEY, remoteActive)
            .putInt(REMOTE_PROFILE_COUNT_KEY, profiles.size)
            .apply()
        if (missingLocalEntry != null) {
            // The profile we follow was deleted on the phone; re-align at the next cold start.
            remoteSelectionPrefs(context).edit().remove(LOCAL_CHOICE_KEY).apply()
        }
        return true
    }

    /**
     * True when this profile has already stored something. A watch that has never received a
     * store can adopt the phone's selection safely; one with data cannot, because its screens
     * are already bound to that profile.
     */
    fun hasStoredData(context: Context, profileId: String): Boolean =
        File(directory(context, profileId), WORKOUT_STORE_FILE).exists()

    /** The selection the paired phone last published, or null when it never did. */
    fun remoteActiveProfileId(context: Context): String? =
        remoteSelectionPrefs(context).getString(REMOTE_ACTIVE_PROFILE_ID_KEY, null)

    /** Number of profiles in the last valid index received from the phone. */
    fun remoteProfileCount(context: Context): Int? =
        remoteSelectionPrefs(context).getInt(REMOTE_PROFILE_COUNT_KEY, 0).takeIf { it > 0 }

    /** True after the user explicitly selected a profile on this device. */
    fun hasLocalProfileChoice(context: Context): Boolean =
        remoteSelectionPrefs(context).getBoolean(LOCAL_CHOICE_KEY, false)

    /**
     * Observes the persisted phone profile-index marker and immediately reports its current value.
     * A non-null value means a valid phone profile index has been received, not that workout data
     * has necessarily finished syncing.
     */
    fun observeRemoteActiveProfileId(
        context: Context,
        onChanged: (String?) -> Unit,
    ): AutoCloseable {
        val preferences = remoteSelectionPrefs(context)
        val mainHandler = Handler(Looper.getMainLooper())
        val active = AtomicBoolean(true)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { prefs, key ->
            if (key == REMOTE_ACTIVE_PROFILE_ID_KEY) {
                val remoteId = prefs.getString(REMOTE_ACTIVE_PROFILE_ID_KEY, null)
                mainHandler.post {
                    if (active.get()) onChanged(remoteId)
                }
            }
        }
        preferences.registerOnSharedPreferenceChangeListener(listener)
        mainHandler.post {
            if (active.get()) {
                onChanged(preferences.getString(REMOTE_ACTIVE_PROFILE_ID_KEY, null))
            }
        }
        return AutoCloseable {
            active.set(false)
            preferences.unregisterOnSharedPreferenceChangeListener(listener)
        }
    }

    /** Observes profile-list writes as well as phone selection changes. */
    fun observeProfileIndex(
        context: Context,
        onChanged: (ProfileIndex) -> Unit,
    ): AutoCloseable {
        val app = context.applicationContext
        val preferences = remoteSelectionPrefs(app)
        val mainHandler = Handler(Looper.getMainLooper())
        val active = AtomicBoolean(true)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, key ->
            if (key == PROFILE_INDEX_REVISION_KEY || key == REMOTE_ACTIVE_PROFILE_ID_KEY ||
                key == REMOTE_PROFILE_COUNT_KEY || key == LOCAL_CHOICE_KEY
            ) {
                mainHandler.post {
                    if (active.get()) onChanged(index(app))
                }
            }
        }
        preferences.registerOnSharedPreferenceChangeListener(listener)
        mainHandler.post {
            if (active.get()) onChanged(index(app))
        }
        return AutoCloseable {
            active.set(false)
            preferences.unregisterOnSharedPreferenceChangeListener(listener)
        }
    }

    /**
     * Adopts the selection published by the phone. Safe only at process start, before any
     * profile-dependent state is loaded. Returns true when the selection changed.
     */
    fun alignActiveProfileWithPhone(context: Context): Boolean {
        val prefs = remoteSelectionPrefs(context)
        if (prefs.getBoolean(LOCAL_CHOICE_KEY, false)) return false
        val remoteActive = prefs.getString(REMOTE_ACTIVE_PROFILE_ID_KEY, null) ?: return false
        val current = index(context)
        if (current.activeProfileId == remoteActive) return false
        if (current.profiles.none { it.id == remoteActive }) return false
        return setActiveProfile(context, remoteActive)
    }

    private fun remoteSelectionPrefs(context: Context) =
        context.applicationContext.getSharedPreferences(PROFILE_SYNC_PREFS, Context.MODE_PRIVATE)

    /**
     * Health Connect belongs to one profile: it is tied to the phone's account, so letting every
     * profile write there would mix two people's sessions in one provider.
     */
    fun healthConnectProfileId(context: Context): String {
        val stored = remoteSelectionPrefs(context).getString(HEALTH_CONNECT_PROFILE_KEY, null)
        return stored?.takeIf { id -> index(context).profiles.any { it.id == id } }
            ?: DEFAULT_PROFILE_ID
    }

    fun setHealthConnectProfile(context: Context, profileId: String): Boolean {
        if (index(context).profiles.none { it.id == profileId }) return false
        remoteSelectionPrefs(context).edit().putString(HEALTH_CONNECT_PROFILE_KEY, profileId).apply()
        return true
    }

    /** True when the profile in use on this device is the one that writes to Health Connect. */
    fun isHealthConnectProfile(context: Context): Boolean =
        healthConnectProfileId(context) == activeProfileId(context)

    /** Returns false when [profileId] is not a known profile. */
    fun setActiveProfile(context: Context, profileId: String): Boolean = synchronized(lock) {
        val index = index(context)
        if (index.profiles.none { it.id == profileId }) return@synchronized false
        writeIndex(context, index.copy(activeProfileId = profileId))
        true
    }

    /**
     * Switches profile because the person using this device chose it. Such an explicit choice is
     * never overridden by the paired phone's selection.
     */
    fun setLocallyChosenProfile(context: Context, profileId: String): Boolean {
        if (!setActiveProfile(context, profileId)) return false
        remoteSelectionPrefs(context).edit().putBoolean(LOCAL_CHOICE_KEY, true).apply()
        return true
    }

    fun create(context: Context, name: String): UserProfile = synchronized(lock) {
        val index = index(context)
        val profile = UserProfile(
            id = UUID.randomUUID().toString(),
            name = name.trim().ifEmpty { "Profile ${index.profiles.size + 1}" },
            createdAtEpochMs = System.currentTimeMillis(),
        )
        directory(context, profile.id).mkdirs()
        writeIndex(context, index.copy(profiles = index.profiles + profile))
        profile
    }

    /**
     * Adds a profile with a specific id, used when restoring a backup that carries its own
     * profile ids. Returns false when the id already exists.
     */
    fun ensureProfile(context: Context, profileId: String, name: String): Boolean = synchronized(lock) {
        val index = index(context)
        if (index.profiles.any { it.id == profileId }) return@synchronized false
        directory(context, profileId).mkdirs()
        writeIndex(
            context,
            index.copy(
                profiles = index.profiles + UserProfile(
                    id = profileId,
                    name = name.trim().ifEmpty { "Profile" },
                )
            )
        )
        true
    }

    fun rename(context: Context, profileId: String, name: String) = synchronized(lock) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) return@synchronized
        val index = index(context)
        writeIndex(
            context,
            index.copy(
                profiles = index.profiles.map {
                    if (it.id == profileId) it.copy(name = trimmed) else it
                }
            )
        )
    }

    /** Deletes a non-active profile and all of its data. Returns false when refused. */
    fun delete(context: Context, profileId: String): Boolean = synchronized(lock) {
        val index = index(context)
        if (profileId == index.activeProfileId) return@synchronized false
        if (index.profiles.none { it.id == profileId }) return@synchronized false
        directory(context, profileId).deleteRecursively()
        SQLITE_SIDECARS.forEach { suffix ->
            File(context.getDatabasePath(databaseName(profileId)).path + suffix).delete()
        }
        writeIndex(context, index.copy(profiles = index.profiles.filterNot { it.id == profileId }))
        true
    }

    private fun readIndex(context: Context): ProfileIndex {
        val file = indexFile(context)
        if (!file.exists()) {
            // First run with profiles: adopt whatever the single-user install already had.
            adoptLegacyData(context)
            val index = ProfileIndex(
                activeProfileId = DEFAULT_PROFILE_ID,
                profiles = listOf(
                    UserProfile(
                        id = DEFAULT_PROFILE_ID,
                        name = DEFAULT_PROFILE_NAME,
                        createdAtEpochMs = System.currentTimeMillis(),
                    )
                ),
            )
            writeIndex(context, index)
            return index
        }

        val parsed = runCatching { gson.fromJson(file.readText(), ProfileIndex::class.java) }
            .getOrNull()
        // Gson bypasses constructors, so a truncated file can hand back a null list.
        val profiles: List<UserProfile> = parsed?.profiles?.filterNotNull().orEmpty()
        if (profiles.isEmpty()) {
            return rebuildIndexFromDirectories(context, file)
        }
        val active = parsed?.activeProfileId
        return if (active == null || profiles.none { it.id == active }) {
            ProfileIndex(activeProfileId = profiles.first().id, profiles = profiles)
        } else {
            ProfileIndex(activeProfileId = active, profiles = profiles)
        }
    }

    /**
     * Adopts the single-user install: the root store stays where it is and becomes the shared
     * content file, and the default profile inherits the personal half of it so the existing
     * user keeps their body metrics. The legacy database becomes the default profile's database.
     */
    private fun adoptLegacyData(context: Context) {
        val defaultDir = File(File(context.filesDir, PROFILES_DIR), DEFAULT_PROFILE_ID).apply { mkdirs() }
        File(context.filesDir, WORKOUT_STORE_FILE).takeIf { it.exists() }?.let { legacy ->
            val legacyStore = runCatching { fromJSONToWorkoutStore(legacy.readText()) }.getOrNull()
            if (legacyStore != null) {
                File(defaultDir, WORKOUT_STORE_FILE)
                    .writeText(fromWorkoutStoreToJSON(legacyStore.personalSettingsOnly()))
            }
        }

        val legacyDatabase = context.getDatabasePath(LEGACY_DATABASE_NAME)
        if (!legacyDatabase.exists()) return
        val target = context.getDatabasePath(databaseName(DEFAULT_PROFILE_ID))
        SQLITE_SIDECARS.forEach { suffix ->
            File(legacyDatabase.path + suffix).takeIf { it.exists() }
                ?.renameTo(File(target.path + suffix))
        }
    }

    private fun indexFile(context: Context) = File(File(context.filesDir, PROFILES_DIR), INDEX_FILE)

    private fun stamp(file: File): Long =
        if (file.exists()) file.lastModified() * 31 + file.length() else Long.MIN_VALUE

    /**
     * Salvages an unreadable index by listing the profile directories, so a corrupt index
     * never hides data that is still on disk.
     */
    private fun rebuildIndexFromDirectories(context: Context, file: File): ProfileIndex {
        if (file.exists()) {
            file.renameTo(File(file.path + INDEX_CORRUPT_SUFFIX))
        }
        val recovered = File(context.filesDir, PROFILES_DIR)
            .listFiles()
            ?.filter { it.isDirectory }
            ?.sortedBy { it.name }
            ?.mapIndexed { position, directory ->
                UserProfile(
                    id = directory.name,
                    name = if (directory.name == DEFAULT_PROFILE_ID) DEFAULT_PROFILE_NAME else "Profile ${position + 1}",
                )
            }
            .orEmpty()

        val index = if (recovered.isEmpty()) {
            ProfileIndex(
                activeProfileId = DEFAULT_PROFILE_ID,
                profiles = listOf(UserProfile(DEFAULT_PROFILE_ID, DEFAULT_PROFILE_NAME)),
            )
        } else {
            ProfileIndex(
                activeProfileId = recovered.firstOrNull { it.id == DEFAULT_PROFILE_ID }?.id
                    ?: recovered.first().id,
                profiles = recovered,
            )
        }
        writeIndex(context, index)
        return index
    }

    private fun writeIndex(context: Context, index: ProfileIndex) {
        val file = indexFile(context)
        file.parentFile?.mkdirs()
        val temporary = File(file.parentFile, "${file.name}.tmp")
        temporary.writeText(gson.toJson(index))
        if (!temporary.renameTo(file)) {
            file.delete()
            temporary.renameTo(file)
        }
        // Refresh the cache here so two writes in the same millisecond cannot serve a stale
        // index: the file timestamp has millisecond resolution.
        cachedIndex = index
        cachedStamp = stamp(file)
        val preferences = remoteSelectionPrefs(context)
        preferences.edit()
            .putLong(
                PROFILE_INDEX_REVISION_KEY,
                preferences.getLong(PROFILE_INDEX_REVISION_KEY, 0L) + 1L,
            )
            .apply()
    }
}
