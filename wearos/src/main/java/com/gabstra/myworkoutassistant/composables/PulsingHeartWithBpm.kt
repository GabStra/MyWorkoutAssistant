package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp


@Composable
fun PulsingHeartWithBpm(
    modifier: Modifier = Modifier,
    bpm: Int,
    tint: Color,
    size: Dp = 15.dp //12.5.dp
) {
    val shouldPulse = bpm > 0

    val scale = if (shouldPulse) {
        val beatDuration = 60000 / bpm
        // Realistic heartbeat timing: systole (contraction) ~33%, diastole (relaxation) ~67%
        val systoleDuration = (beatDuration * 0.33f).toInt()
        val infiniteTransition = rememberInfiniteTransition(label = "heart-transition")

        infiniteTransition.animateFloat(
            initialValue = 0.8f,
            targetValue = 1.2f,
            animationSpec = infiniteRepeatable(
                animation = keyframes {
                    durationMillis = beatDuration
                    // Systole: quick, sharp contraction (fast out, linear in for sharpness)
                    0.8f at 0 using FastOutLinearInEasing
                    1.2f at systoleDuration using FastOutLinearInEasing
                    // Diastole: slower, smoother relaxation (linear out, slow in for smoothness)
                    0.8f at beatDuration using FastOutSlowInEasing
                },
                repeatMode = RepeatMode.Restart
            ),
            label = "heart-scale"
        ).value
    } else {
        1f
    }

    HeartIcon(
        modifier = modifier
            .size(size)
            .scale(scale),
        tint = tint
    )
}
