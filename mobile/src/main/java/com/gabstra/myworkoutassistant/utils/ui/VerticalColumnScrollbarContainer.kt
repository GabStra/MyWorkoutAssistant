package com.gabstra.myworkoutassistant

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier

@Composable
fun Modifier.verticalColumnScrollbarContainer(
    scrollState: ScrollState
): Modifier = this
    .verticalColumnScrollbar(scrollState)
    .verticalScroll(scrollState)
    .padding(horizontal = Spacing.lg)
