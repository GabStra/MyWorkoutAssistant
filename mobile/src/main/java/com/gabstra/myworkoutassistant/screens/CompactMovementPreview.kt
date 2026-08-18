package com.gabstra.myworkoutassistant.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.MotionPhotosOff
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef

@Composable
fun CompactMovementPreview(
    movementRef: ExerciseMovementRef?,
    contentDescription: String,
    modifier: Modifier = Modifier,
) {
    val hostView = LocalView.current
    var isVisible by remember { mutableStateOf(false) }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(10.dp))
            .onGloballyPositioned { coordinates ->
                val bounds = coordinates.boundsInWindow()
                isVisible = bounds.bottom > 0f && bounds.top < hostView.height.toFloat()
            }
            .semantics { this.contentDescription = contentDescription },
        contentAlignment = Alignment.Center,
    ) {
        if (isVisible && movementRef != null) {
            ExerciseMovementPreviewPage(
                movementRef = movementRef,
                modifier = Modifier.fillMaxSize(),
                dragRotationEnabled = false,
                compactStatusIcons = true,
                listThumbnail = true,
            )
        } else if (movementRef == null) {
            Icon(
                imageVector = Icons.Outlined.MotionPhotosOff,
                contentDescription = null,
                modifier = Modifier.size(24.dp),
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
