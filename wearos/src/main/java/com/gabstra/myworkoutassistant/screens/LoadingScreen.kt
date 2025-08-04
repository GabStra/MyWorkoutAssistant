package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.wear.compose.material.MaterialTheme
import com.gabstra.myworkoutassistant.composables.KeepOn
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.data.AppViewModel

@Composable
fun LoadingScreen(appViewModel: AppViewModel, text: String = "Loading", extraContent: @Composable () -> Unit = {}) {
    BackHandler(true) {
        // Do nothing
    }

    KeepOn(appViewModel) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            LoadingText(baseText = text)
            extraContent()
        }
    }
}