package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.data.AppViewModel

@Composable
fun LoadingScreen(
    appViewModel: AppViewModel,
    text: String = "Loading",
    extraContent: @Composable () -> Unit = {},
) {
    BackHandler(true) {
        // Do nothing
    }

    FullScreenLoadingIndicator(
        text = text,
        content = extraContent,
    )
}
