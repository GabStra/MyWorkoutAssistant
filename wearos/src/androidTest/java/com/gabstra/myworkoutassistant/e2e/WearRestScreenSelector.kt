package com.gabstra.myworkoutassistant.e2e

import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.BySelector
import com.gabstra.myworkoutassistant.R

/**
 * Locates the rest screen through the same localized accessibility description the screen
 * exposes to users.
 *
 * The rest screen must not append an English-only marker to its content description, because
 * that leaks untranslated text into non-English UIs. Resolving the app resource here keeps the
 * selector aligned with the rendered locale while preserving the English behavior.
 */
object WearRestScreenSelector {
    fun byDescription(): BySelector {
        val description = InstrumentationRegistry.getInstrumentation()
            .targetContext
            .getString(R.string.wear_rest_screen_description)
        return By.descContains(description)
    }
}
