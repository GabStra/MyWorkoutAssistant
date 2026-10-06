package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.Icon
import androidx.wear.compose.material3.IconButton

@Composable
fun PreviousNextNavigationHeader(
    modifier: Modifier = Modifier,
    canSelectPrevious: Boolean,
    canSelectNext: Boolean,
    onSelectPrevious: () -> Unit,
    onSelectNext: () -> Unit,
    buttonSize: Dp = 48.dp,
    iconSize: Dp = 32.dp,
    content: @Composable () -> Unit,
) {
    Box(
        modifier = modifier,
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier.padding(horizontal = 44.dp),
            contentAlignment = Alignment.Center,
        ) {
            content()
        }
        IconButton(
            onClick = onSelectPrevious,
            modifier = Modifier
                .align(Alignment.CenterStart)
                .size(buttonSize),
            enabled = canSelectPrevious,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowLeft,
                contentDescription = "Previous",
                modifier = Modifier.size(iconSize),
            )
        }
        IconButton(
            onClick = onSelectNext,
            modifier = Modifier
                .align(Alignment.CenterEnd)
                .size(buttonSize),
            enabled = canSelectNext,
        ) {
            Icon(
                imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
                contentDescription = "Next",
                modifier = Modifier.size(iconSize),
            )
        }
    }
}
