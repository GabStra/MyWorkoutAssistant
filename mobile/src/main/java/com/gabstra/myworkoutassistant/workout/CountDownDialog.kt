package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@Composable
fun CountDownDialog(
    show: Boolean,
    time: Int,
) {
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.displayLarge.copy(fontWeight = W700) }

    if(show) {
        Dialog(
            onDismissRequest = { },
            properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false , usePlatformDefaultWidth = false)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.75f)),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "$time",
                    textAlign = TextAlign.Center,
                    style = itemStyle
                )
            }
        }
    }
}