package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisGuidelineComponent
import com.patrykandpatrick.vico.compose.common.DashedShape
import com.patrykandpatrick.vico.compose.common.Fill

@Composable
internal fun rememberPressedChartGuideline() =
    rememberAxisGuidelineComponent(
        fill = Fill(Color.White),
        thickness = 1.dp,
        shape = DashedShape(),
    )
