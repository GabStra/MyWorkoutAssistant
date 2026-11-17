package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme

object WorkoutPagerLayoutTokens {
    val WorkoutHeaderTopPadding = 7.5.dp
    val WorkoutHeaderHeight = 25.dp
    // HR overlay's bottom readout: 25dp box offset 7.5dp → glyph tops ~28dp above the screen
    // edge; set screens add 4dp inside the scroll. 40dp puts the mask's bottom fade tail
    // ~16dp clear of the "142 / Z2" text (smaller steps of 24/30dp read as unchanged).
    val HorizontalPagerBottomContentPadding = 40.dp
    val BottomIndicatorSpacing = 7.5.dp
    val ExerciseTitleHorizontalPadding = 37.5.dp
    val OverlayContentHorizontalPadding = 10.dp
}

val WorkoutPagerHeaderReservedHeight =
    WorkoutPagerLayoutTokens.WorkoutHeaderTopPadding + WorkoutPagerLayoutTokens.WorkoutHeaderHeight

val WorkoutPagerPageSafeAreaPadding = PaddingValues(
    top = WorkoutPagerHeaderReservedHeight,
    bottom = WorkoutPagerLayoutTokens.HorizontalPagerBottomContentPadding
)

@Composable
fun workoutPagerTitleTextStyle(): TextStyle =
    MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)

@Composable
fun workoutSectionLabelTextStyle(): TextStyle =
    MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.SemiBold)
