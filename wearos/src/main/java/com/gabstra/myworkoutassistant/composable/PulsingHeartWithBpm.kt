package com.gabstra.myworkoutassistant.composable

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.unit.dp

@Composable
fun PulsingHeartWithBpm(
    bpm: Int,
) {
    // Convert BPM to duration in milliseconds for each beat
    val beatDuration = remember(bpm) {
        60000 / bpm
    }

    val infiniteTransition = rememberInfiniteTransition("animation")
    val scale by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 1.2f,
        animationSpec = infiniteRepeatable(
            // Set the duration of the animation based on the BPM
            animation = tween(beatDuration, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label="animation"
    )

    HeartIcon(modifier = Modifier
        .size(12.dp)
        .scale(if (beatDuration != 0) scale else 1f))
}
