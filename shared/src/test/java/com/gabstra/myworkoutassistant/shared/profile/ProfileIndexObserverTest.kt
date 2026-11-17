package com.gabstra.myworkoutassistant.shared.profile

import android.content.Context
import android.os.Looper
import androidx.test.core.app.ApplicationProvider
import com.google.gson.Gson
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class ProfileIndexObserverTest {

    @Test
    fun indexGrowthNotifiesObserver() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val localActiveId = Profiles.activeProfileId(context)
        val localProfile = Profiles.profiles(context).single { it.id == localActiveId }
        val observed = mutableListOf<ProfileIndex>()
        val observer = Profiles.observeProfileIndex(context) { observed += it }

        shadowOf(Looper.getMainLooper()).idle()
        assertTrue(observed.isNotEmpty())
        observed.clear()

        // First phone receipt: one profile, so this device now knows a remote selection exists.
        Profiles.applyRemoteIndexJson(
            context,
            Gson().toJson(
                ProfileIndex(activeProfileId = localActiveId, profiles = listOf(localProfile)),
            ),
        )
        shadowOf(Looper.getMainLooper()).idle()

        assertNotNull(Profiles.remoteActiveProfileId(context))
        assertEquals(localActiveId, Profiles.remoteActiveProfileId(context))
        assertEquals(1, Profiles.profiles(context).size)
        assertEquals(localActiveId, Profiles.activeProfileId(context))
        assertTrue(observed.isNotEmpty())
        observed.clear()

        // The phone's list grows while its selection stays the same: the observer must still fire.
        val addedProfile = UserProfile(UUID.randomUUID().toString(), "Phone Profile")
        Profiles.applyRemoteIndexJson(
            context,
            Gson().toJson(
                ProfileIndex(
                    activeProfileId = localActiveId,
                    profiles = listOf(localProfile, addedProfile),
                ),
            ),
        )
        shadowOf(Looper.getMainLooper()).idle()

        assertEquals(2, Profiles.profiles(context).size)
        assertEquals(localActiveId, Profiles.remoteActiveProfileId(context))
        assertEquals(2, Profiles.remoteProfileCount(context))
        assertEquals(localActiveId, Profiles.activeProfileId(context))
        assertTrue(observed.isNotEmpty())
        assertEquals(2, observed.last().profiles.size)
        assertEquals(localActiveId, observed.last().activeProfileId)
        observer.close()
    }

    @Test
    fun retainedWatchOnlyProfileDoesNotCountAsPhoneProfile() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val localProfile = Profiles.profiles(context).single()
        val phoneProfile = UserProfile(UUID.randomUUID().toString(), "Phone Profile")
        assertEquals(false, Profiles.hasLocalProfileChoice(context))

        assertTrue(
            Profiles.applyRemoteIndexJson(
                context,
                Gson().toJson(ProfileIndex(localProfile.id, listOf(localProfile))),
            ),
        )
        assertTrue(
            Profiles.applyRemoteIndexJson(
                context,
                Gson().toJson(ProfileIndex(phoneProfile.id, listOf(phoneProfile))),
            ),
        )

        assertEquals(2, Profiles.profiles(context).size)
        assertEquals(1, Profiles.remoteProfileCount(context))
        assertEquals(localProfile.id, Profiles.activeProfileId(context))
        assertEquals(false, Profiles.hasLocalProfileChoice(context))
        assertTrue(Profiles.setLocallyChosenProfile(context, phoneProfile.id))
        assertEquals(true, Profiles.hasLocalProfileChoice(context))
    }

    @Test
    fun remoteCountOnlyChangeNotifiesObserverWithUpdatedCount() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val localProfile = Profiles.profiles(context).single()
        val phoneProfile = UserProfile(UUID.randomUUID().toString(), "Phone Profile")
        val observedCounts = mutableListOf<Int?>()
        val observer = Profiles.observeProfileIndex(context) { observedCounts += Profiles.remoteProfileCount(context) }
        shadowOf(Looper.getMainLooper()).idle()
        observedCounts.clear()

        Profiles.applyRemoteIndexJson(
            context,
            Gson().toJson(ProfileIndex(phoneProfile.id, listOf(phoneProfile, localProfile))),
        )
        shadowOf(Looper.getMainLooper()).idle()
        observedCounts.clear()
        val mergedIndex = Profiles.index(context)

        Profiles.applyRemoteIndexJson(
            context,
            Gson().toJson(ProfileIndex(phoneProfile.id, listOf(phoneProfile))),
        )
        shadowOf(Looper.getMainLooper()).idle()

        assertEquals(mergedIndex, Profiles.index(context))
        assertEquals(1, Profiles.remoteProfileCount(context))
        assertTrue(observedCounts.isNotEmpty())
        assertEquals(1, observedCounts.last())
        observer.close()
    }
}
