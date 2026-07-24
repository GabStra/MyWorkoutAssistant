package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.CircularProgressIndicator
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.shared.MediumDarkGray

@Composable
fun FullScreenLoadingIndicator(
    text: String,
    modifier: Modifier = Modifier,
    progress: Float? = null,
    content: @Composable () -> Unit = {},
) {
    Box(
        modifier = modifier.fillMaxSize(),
        contentAlignment = Alignment.Center,
    ) {
        if (progress == null) {
            CircularProgressIndicator(
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                indicatorColor = MaterialTheme.colorScheme.primary,
                trackColor = MediumDarkGray,
            )
        } else {
            CircularProgressIndicator(
                progress = progress.coerceIn(0f, 1f),
                modifier = Modifier.fillMaxSize(),
                strokeWidth = 4.dp,
                indicatorColor = MaterialTheme.colorScheme.primary,
                trackColor = MediumDarkGray,
            )
        }
        Column(
            modifier = Modifier.padding(horizontal = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            LoadingText(baseText = text)
            content()
        }
    }
}
