package com.gabstra.myworkoutassistant.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.CircularProgressIndicator
import com.gabstra.myworkoutassistant.composables.LoadingText
import com.gabstra.myworkoutassistant.data.AppViewModel

@Composable
fun LoadingScreen(appViewModel: AppViewModel, text: String = "Loading", extraContent: @Composable () -> Unit = {}) {
    BackHandler(true) {
        // Do nothing
    }

    Column(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(8.dp))
        LoadingText(baseText = text)
        extraContent()
    }
}