package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneLaunchFromWearVerificationTest {

    private companion object {
        const val LIVE_LAUNCH_MODE = "observe_live"
        const val LIVE_LAUNCH_ARG = "phone_launch_from_wear_mode"
    }

    private fun resolvedLaunchTimeoutMs(): Long =
        CrossDeviceSyncTestPrerequisites.resolvedTimeoutMs(timeoutMs = 20_000)

    private fun requireLiveLaunchVerificationOrSkip() {
        assumeTrue(
            "Requires live cross-device launch orchestration. Run via run_cross_device_open_phone_app_e2e.ps1.",
            InstrumentationRegistry.getArguments()
                .getString(LIVE_LAUNCH_ARG)
                ?.equals(LIVE_LAUNCH_MODE, true) == true
        )
    }

    @Test
    fun openPhoneAppFromWear_foregroundsPhoneOnSettingsScreen() {
        requireLiveLaunchVerificationOrSkip()

        val context = ApplicationProvider.getApplicationContext<Context>()
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val driver = PhoneAppDriver(device, context)
        val timeoutMs = resolvedLaunchTimeoutMs()

        device.pressHome()
        device.waitForIdle(1_000)
        val appBackgrounded = device.wait(
            androidx.test.uiautomator.Until.gone(By.pkg(context.packageName).depth(0)),
            5_000
        ) || !device.hasObject(By.pkg(context.packageName).depth(0))
        assertTrue(
            "Expected the phone app to be backgrounded before the Wear launch request.",
            appBackgrounded
        )

        assertTrue(
            "Timed out waiting for the phone app to foreground after the Wear launch request.",
            driver.waitForAppForeground(timeoutMs = timeoutMs)
        )

        driver.dismissStartupPermissionDialogs(timeoutMs = timeoutMs)

        assertTrue(
            "Timed out waiting for the Settings screen after the Wear launch request.",
            driver.waitForForegroundText(text = "Settings", timeoutMs = timeoutMs)
        )
    }
}
