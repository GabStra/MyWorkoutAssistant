package com.gabstra.myworkoutassistant.shared.profile

/** One person using this install. [id] also names the profile's data directory and database. */
data class UserProfile(
    val id: String,
    val name: String,
    val createdAtEpochMs: Long = 0L,
)

/** The profile list plus which one this device is currently looking at. */
data class ProfileIndex(
    val activeProfileId: String,
    val profiles: List<UserProfile>,
    val schemaVersion: Int = CURRENT_SCHEMA_VERSION,
) {
    companion object {
        const val CURRENT_SCHEMA_VERSION = 1
    }
}
