package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.Red


@Composable
fun PulsingHeartWithBpm(
    bpm: Int,
    tint: Color = Red
) {
    val shouldPulse = bpm > 0

    val scale = if (shouldPulse) {
        val beatDuration = 60000 / bpm
        val infiniteTransition = rememberInfiniteTransition(label = "heart-transition")

        infiniteTransition.animateFloat(
            initialValue = 0.8f,
            targetValue = 1.2f,
            animationSpec = infiniteRepeatable(
                animation = tween(durationMillis = beatDuration / 2, easing = FastOutSlowInEasing),
                repeatMode = RepeatMode.Reverse
            ),
            label = "heart-scale"
        ).value
    } else {
        1f
    }

    HeartIcon(
        modifier = Modifier
            .size(15.dp)
            .scale(scale),
        tint = tint
    )
}
