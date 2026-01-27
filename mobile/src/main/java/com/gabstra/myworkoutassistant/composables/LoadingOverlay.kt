package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import kotlinx.coroutines.delay
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.gabstra.myworkoutassistant.Spacing

@Composable
fun rememberDebouncedSavingVisible(isSaving: Boolean, delayMs: Long = 400L): Boolean {
    var show by remember { mutableStateOf(false) }
    LaunchedEffect(isSaving) {
        if (!isSaving) {
            show = false
            return@LaunchedEffect
        }
        delay(delayMs)
        show = true
    }
    return show
}

@Composable
fun LoadingOverlay(isVisible: Boolean, text: String = "Loading...") {
    if (isVisible) {
        val interactionSource = remember { MutableInteractionSource() }
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.75f))
                .clickable(
                    interactionSource = interactionSource,
                    indication = null,
                    onClick = {}
                ),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Spacer(Modifier.height(Spacing.md))
                Text(text = text, style = MaterialTheme.typography.bodyLarge)
            }
        }
    }
}

