package com.gabstra.myworkoutassistant.shared.profile

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutStore
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class ProfilesTest {

    private lateinit var context: Context

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
    }

    @Test
    fun adoptsLegacyStoreIntoSharedContentPlusDefaultProfile() {
        val legacyStore = WorkoutStore(
            workouts = emptyList(),
            equipments = emptyList(),
            accessoryEquipments = emptyList(),
            workoutPlans = emptyList(),
            birthDateYear = 1990,
            weightKg = 82.5,
            progressionPercentageAmount = 2.0,
        )
        val sharedStoreFile = File(context.filesDir, "workout_store.json")
        sharedStoreFile.writeText(fromWorkoutStoreToJSON(legacyStore))

        val legacyDatabase = context.getDatabasePath("app_database_2")
        legacyDatabase.parentFile?.mkdirs()
        legacyDatabase.writeText("db")
        File(legacyDatabase.path + "-wal").writeText("wal")

        val index = Profiles.index(context)

        assertEquals(listOf(Profiles.DEFAULT_PROFILE_ID), index.profiles.map { it.id })
        assertEquals(Profiles.DEFAULT_PROFILE_ID, index.activeProfileId)

        // The root file stays put and becomes the shared content file.
        assertTrue(sharedStoreFile.exists())

        // The default profile inherits the personal half, so the existing user keeps their metrics.
        val personalFile = File(context.filesDir, "profiles/default/workout_store.json")
        assertTrue(personalFile.exists())
        val personal = fromJSONToWorkoutStore(personalFile.readText())
        assertEquals(1990, personal.birthDateYear)
        assertEquals(82.5, personal.weightKg, 0.0)

        assertFalse(legacyDatabase.exists())
        val adoptedDatabase = context.getDatabasePath("app_database_default")
        assertTrue(adoptedDatabase.exists())
        assertTrue(File(adoptedDatabase.path + "-wal").exists())

        // Callers still see one merged store.
        val merged = WorkoutStoreRepository(
            Profiles.directory(context, Profiles.DEFAULT_PROFILE_ID),
            context.filesDir,
        ).getWorkoutStore()
        assertEquals(1990, merged.birthDateYear)
        assertEquals(82.5, merged.weightKg, 0.0)
    }

    @Test
    fun createsSwitchesRenamesAndDeletesProfiles() {
        Profiles.index(context)
        val second = Profiles.create(context, "Alice")

        assertEquals(listOf("Profile 1", "Alice"), Profiles.profiles(context).map { it.name })
        assertTrue(Profiles.setActiveProfile(context, second.id))
        assertEquals(second.id, Profiles.activeProfileId(context))

        assertFalse("the active profile must not be deletable", Profiles.delete(context, second.id))

        Profiles.rename(context, second.id, "Alice B.")
        assertEquals("Alice B.", Profiles.profiles(context).last().name)

        assertTrue(Profiles.setActiveProfile(context, Profiles.DEFAULT_PROFILE_ID))
        assertTrue(Profiles.delete(context, second.id))
        assertEquals(1, Profiles.profiles(context).size)
        assertFalse(File(context.filesDir, "profiles/${second.id}").exists())
    }

    @Test
    fun rebuildsACorruptIndexFromTheProfileDirectories() {
        Profiles.index(context)
        val second = Profiles.create(context, "Bob")

        File(context.filesDir, "profiles/index.json").writeText("{not json")

        val recovered = Profiles.profiles(context)
        assertEquals(
            setOf(Profiles.DEFAULT_PROFILE_ID, second.id),
            recovered.map { it.id }.toSet(),
        )
        assertTrue(File(context.filesDir, "profiles/index.json.corrupt").exists())
    }

    @Test
    fun payloadProfileResolutionDistinguishesMissingFromDeleted() {
        Profiles.index(context)
        val second = Profiles.create(context, "Alice")

        // A payload without the key predates profiles, so it belongs to the active profile.
        assertEquals(
            Profiles.activeProfileId(context),
            Profiles.resolvePayloadProfile(context, null),
        )
        assertEquals(second.id, Profiles.resolvePayloadProfile(context, second.id))
        // A named profile that no longer exists must be dropped, never redirected.
        assertNull(Profiles.resolvePayloadProfile(context, "profile-deleted-here"))
    }

    @Test
    fun healthConnectWritesOnlyForItsOwnProfile() {
        Profiles.index(context)
        val second = Profiles.create(context, "Alice")

        // The default profile owns Health Connect until told otherwise.
        assertTrue(Profiles.isHealthConnectProfile(context))

        assertTrue(Profiles.setHealthConnectProfile(context, second.id))
        assertFalse(Profiles.isHealthConnectProfile(context))

        assertTrue(Profiles.setActiveProfile(context, second.id))
        assertTrue(Profiles.isHealthConnectProfile(context))
    }

    @Test
    fun remoteIndexUpdatesTheListWithoutSwitchingTheLocalSelection() {
        Profiles.index(context)
        val alice = Profiles.create(context, "Alice")
        assertTrue(Profiles.setLocallyChosenProfile(context, alice.id))
        assertNull(Profiles.remoteActiveProfileId(context))

        assertFalse(
            Profiles.applyRemoteIndexJson(
                context,
                """{"activeProfileId":"${Profiles.DEFAULT_PROFILE_ID}","profiles":[]}""",
            ),
        )
        assertNull(Profiles.remoteActiveProfileId(context))

        val remoteJson = """
            {"activeProfileId":"${Profiles.DEFAULT_PROFILE_ID}",
             "profiles":[
               {"id":"${Profiles.DEFAULT_PROFILE_ID}","name":"Profile 1"},
               {"id":"${alice.id}","name":"Alice Renamed"}
             ]}
        """.trimIndent()

        assertTrue(Profiles.applyRemoteIndexJson(context, remoteJson))
        assertEquals(Profiles.DEFAULT_PROFILE_ID, Profiles.remoteActiveProfileId(context))

        // The phone's selection must not rebind a running app.
        assertEquals(alice.id, Profiles.activeProfileId(context))
        assertEquals("Alice Renamed", Profiles.profiles(context).last().name)
    }
}
