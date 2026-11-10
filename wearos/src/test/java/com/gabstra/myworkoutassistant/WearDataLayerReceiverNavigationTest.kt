package com.gabstra.myworkoutassistant

import android.app.Activity
import android.content.Intent
import androidx.navigation.NavHostController
import androidx.navigation.createGraph
import androidx.wear.compose.navigation.WearNavigator
import androidx.wear.compose.navigation.composable
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import io.mockk.mockk
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, sdk = [35], application = android.app.Application::class)
class WearDataLayerReceiverNavigationTest {
    @Test
    fun connectingAndTransferEventsKeepTheSameLoadingEntry() {
        val context = RuntimeEnvironment.getApplication()
        val navController = NavHostController(context).apply {
            navigatorProvider.addNavigator(WearNavigator())
            graph = createGraph(startDestination = Screen.WorkoutSelection.route) {
                composable(Screen.WorkoutSelection.route) {}
                composable(Screen.Loading.route) {}
            }
        }
        val receiver = WearDataLayerReceiver(
            navController = navController,
            appViewModel = mockk<AppViewModel>(relaxed = true),
            workoutStoreRepository = mockk<WorkoutStoreRepository>(),
            activity = mockk<Activity>(),
        )
        val connecting = Intent().apply {
            putExtra(DataLayerListenerService.APP_BACKUP_PROGRESS_UPDATE, "0.0")
            putExtra(DataLayerListenerService.APP_BACKUP_PHASE_UPDATE, SyncPhase.CONNECTING.name)
        }
        val transferStart = Intent().apply {
            putExtra(DataLayerListenerService.APP_BACKUP_START_JSON, "{}")
            putExtra(DataLayerListenerService.APP_BACKUP_START_ACCEPTED, true)
        }

        receiver.onReceive(context, connecting)
        val loadingEntry = navController.currentBackStackEntry
        assertEquals(Screen.Loading.route, loadingEntry?.destination?.route)
        receiver.onReceive(context, connecting)
        assertSame(loadingEntry, navController.currentBackStackEntry)

        receiver.onReceive(context, transferStart)
        receiver.onReceive(context, transferStart)
        assertSame(loadingEntry, navController.currentBackStackEntry)
    }
}
