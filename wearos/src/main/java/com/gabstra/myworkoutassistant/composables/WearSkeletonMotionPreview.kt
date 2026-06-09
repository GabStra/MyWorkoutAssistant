package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.motionrenderer.SkeletonMotionPreview

@Composable
fun WearSkeletonMotionPreview(
    skeletonJson: String,
    modifier: Modifier = Modifier,
    animated: Boolean = true,
    viewYawDegrees: Float = -28f,
    viewPitchDegrees: Float = 15f,
    orbitView: Boolean = false,
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
    )
}
