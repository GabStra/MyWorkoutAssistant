package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview

private const val WearMovementLoopRestartFadeMillis = 250

@Composable
fun WearSkeletonMotionPreview(
    skeletonJson: String,
    modifier: Modifier = Modifier,
    animated: Boolean = true,
    viewYawDegrees: Float = -28f,
    viewPitchDegrees: Float = 15f,
    orbitView: Boolean = false,
    loopRestartFadeMillis: Int = WearMovementLoopRestartFadeMillis,
    dragRotationEnabled: Boolean = true,
    dragRotationHorizontalInset: Dp = 0.dp,
    isRenderingActive: Boolean = true,
) {
    SkeletonMotionPreview(
        skeletonJson = skeletonJson,
        modifier = modifier,
        backgroundColor = MaterialTheme.colorScheme.background,
        primaryFill = MaterialTheme.colorScheme.primary,
        animated = animated,
        viewYawDegrees = viewYawDegrees,
        viewPitchDegrees = viewPitchDegrees,
        orbitView = orbitView,
        loopRestartFadeMillis = loopRestartFadeMillis,
        dragRotationEnabled = dragRotationEnabled,
        dragRotationHorizontalInset = dragRotationHorizontalInset,
        isRenderingActive = isRenderingActive,
    )
}
