package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.compositeOver
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.ui.theme.DarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumDarkGray
import com.gabstra.myworkoutassistant.ui.theme.MediumGray

@Composable
fun DarkModeContainer(
    modifier: Modifier = Modifier,
    whiteOverlayAlpha: Float = 0f,
    isRounded: Boolean = true,
    content: @Composable () -> Unit,
) {
    Box(
        modifier = modifier
            .then(if (isRounded) Modifier.clip(RoundedCornerShape(10.dp)) else Modifier)
            .background(MediumDarkGray)
            .wrapContentSize(),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}