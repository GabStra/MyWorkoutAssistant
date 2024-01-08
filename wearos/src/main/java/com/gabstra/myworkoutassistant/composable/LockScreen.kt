package com.gabstra.myworkoutassistant.composable

import android.util.Log
import android.view.MotionEvent
import android.widget.Toast
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.LockOpen
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.wear.compose.material.ExperimentalWearMaterialApi
import androidx.wear.compose.material.FractionalThreshold
import androidx.wear.compose.material.Icon
import androidx.wear.compose.material.rememberSwipeableState
import androidx.wear.compose.material.swipeable
import com.gabstra.myworkoutassistant.data.VibrateOnce
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sqrt

@OptIn(ExperimentalComposeUiApi::class, ExperimentalFoundationApi::class,
    ExperimentalWearMaterialApi::class
)
@Composable
fun LockScreen(
    show: Boolean = false,
    onUnlock: () -> Unit,
) {
    val state = rememberSwipeableState(initialValue = 0)
    val context = LocalContext.current

    var touchCounter by remember { mutableIntStateOf(0) }

    LaunchedEffect(state.targetValue) {
        if(state.targetValue == 1){
            VibrateOnce(context)
            onUnlock()
        }
    }

    LaunchedEffect(show){
        state.snapTo(0)
    }

    val sizePx = with(LocalDensity.current) { 100.dp.toPx() }
    val anchors = mapOf(0f to 0, sizePx to 1)

    if (show) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(22.dp)
                .clickable {
                    if(touchCounter>=5){
                        Toast.makeText(context, "Unlock by swiping right", Toast.LENGTH_SHORT).show()
                        touchCounter=0
                    }else{
                        touchCounter++
                    }
                }.swipeable(
                    state = state,
                    anchors = anchors,
                    thresholds = { _, _ -> FractionalThreshold(0.3f) },
                    orientation = Orientation.Horizontal
                ),
            contentAlignment = Alignment.TopCenter
        ){
            Icon(
                imageVector = Icons.Filled.Lock,
                contentDescription = "Lock Icon",
                modifier = Modifier
                    .size(15.dp)
            )
        }
    }
}