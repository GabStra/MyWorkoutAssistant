package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme

object WorkoutPagerLayoutTokens {
    val WorkoutHeaderTopPadding = 7.5.dp
    val WorkoutHeaderHeight = 27.5.dp
    val HorizontalPagerBottomContentPadding = 27.5.dp
    val ExerciseTitleHorizontalPadding = 22.5.dp
    val OverlayContentHorizontalPadding = 14.dp
    val HeartRateZoneVisualScale = 1f
    val ExerciseIndicatorVisualScale = 1f
    val HeartRateReadoutAnchorOffsetX = 0.dp
}

val WorkoutPagerHeaderReservedHeight =
    WorkoutPagerLayoutTokens.WorkoutHeaderTopPadding + WorkoutPagerLayoutTokens.WorkoutHeaderHeight

val WorkoutPagerPageSafeAreaPadding = PaddingValues(
    top = WorkoutPagerHeaderReservedHeight,
    bottom = WorkoutPagerLayoutTokens.HorizontalPagerBottomContentPadding
)

fun Modifier.overlayVisualScale(scale: Float): Modifier =
    graphicsLayer {
        scaleX = scale
        scaleY = scale
    }

@Composable
fun workoutPagerTitleTextStyle(): TextStyle =
    MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.SemiBold)
