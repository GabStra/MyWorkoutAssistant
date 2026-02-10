package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.text.font.FontWeight.Companion.W700
import androidx.compose.ui.text.style.TextAlign

@Composable
fun CountdownOverlayBox(
    show: Boolean,
    time: Int,
) {
    val typography = MaterialTheme.typography
    val itemStyle = remember(typography) { typography.displayLarge.copy(fontWeight = W700) }

    if (show) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.75f)),
            contentAlignment = Alignment.Center
        ) {
            Surface(
                color = MaterialTheme.colorScheme.surface,
                shape = MaterialTheme.shapes.medium
            ) {
                Text(
                    modifier = Modifier.padding(horizontal = 28.dp, vertical = 20.dp),
                    text = "$time",
                    textAlign = TextAlign.Center,
                    style = itemStyle
                )
            }
        }
    }
}
