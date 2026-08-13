package com.gabstra.myworkoutassistant.workout

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

@Composable
internal fun mobileWorkoutPageTitleStyle(): TextStyle =
    MaterialTheme.typography.displaySmall.copy(
        fontSize = 36.sp,
        lineHeight = 40.sp,
        fontWeight = FontWeight.SemiBold,
    )
