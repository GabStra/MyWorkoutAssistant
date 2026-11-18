package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.composables.FullScreenLoadingIndicator
import com.gabstra.myworkoutassistant.data.AppViewModel

@Composable
fun LoadingScreen(
    appViewModel: AppViewModel,
    text: String? = null,
    extraContent: @Composable () -> Unit = {},
) {
    BackHandler(true) {
        // Do nothing
    }

    FullScreenLoadingIndicator(
        text = text ?: stringResource(R.string.wear_loading),
        content = extraContent,
    )
}
