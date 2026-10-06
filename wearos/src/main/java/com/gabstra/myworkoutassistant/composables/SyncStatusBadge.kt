package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Sync
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.data.AppViewModel

@Composable
fun SyncStatusBadge(
    viewModel: AppViewModel,
    modifier: Modifier = Modifier
) {
    val syncStatus by viewModel.syncStatus.collectAsState()
    val infiniteTransition = rememberInfiniteTransition(label = "sync icon rotation")
    val rotationDegrees by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1200, easing = LinearEasing)
        ),
        label = "sync icon rotation degrees"
    )

    AnimatedVisibility(
        visible = syncStatus == AppViewModel.SyncStatus.Syncing,
        modifier = modifier.padding(top = 8.dp),
        enter = slideInVertically(
            animationSpec = tween(durationMillis = 220),
            initialOffsetY = { -it }
        ) + fadeIn(animationSpec = tween(durationMillis = 120)),
        exit = slideOutVertically(
            animationSpec = tween(durationMillis = 180),
            targetOffsetY = { -it }
        ) + fadeOut(animationSpec = tween(durationMillis = 120))
    ) {
        Box(
            modifier = Modifier
                .size(28.dp)
                .background(
                    color = Color.Black,
                    shape = CircleShape
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Default.Sync,
                contentDescription = null,
                modifier = Modifier
                    .size(18.dp)
                    .rotate(rotationDegrees)
                    .semantics { contentDescription = "Syncing" },
                tint = MaterialTheme.colorScheme.primary
            )
        }
    }
}
