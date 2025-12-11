package com.gabstra.myworkoutassistant.composables

import androidx.compose.animation.AnimatedContentScope
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState

/**
 * Custom NavHost that allows per-route control over swipe-to-go-back gestures.
 * 
 * @param navController The NavHostController for navigation
 * @param startDestination The route for the start destination
 * @param modifier Modifier to be applied to the NavHost
 * @param enterTransition Transition animation when entering a destination
 * @param exitTransition Transition animation when exiting a destination
 * @param popEnterTransition Transition animation when entering via pop
 * @param popExitTransition Transition animation when exiting via pop
 * @param builder Lambda to build the navigation graph
 */
@Composable
fun CustomNavHost(
    navController: NavHostController,
    startDestination: String,
    modifier: Modifier = Modifier,
    enterTransition: (AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition)? = null,
    exitTransition: (AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition)? = null,
    popEnterTransition: (AnimatedContentTransitionScope<NavBackStackEntry>.() -> EnterTransition)? = null,
    popExitTransition: (AnimatedContentTransitionScope<NavBackStackEntry>.() -> ExitTransition)? = null,
    builder: NavGraphBuilder.(MutableMap<String, Boolean>) -> Unit
) {
    // Track swipe preferences per route
    val routeSwipePreferences = remember { mutableStateMapOf<String, Boolean>() }
    
    // Observe current route
    val currentBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = currentBackStackEntry?.destination?.route ?: startDestination
    val enableSwipeToGoBack = routeSwipePreferences[currentRoute] ?: false
    
    // Threshold for back swipe detection (right-to-left)
    val swipeThreshold = with(LocalDensity.current) { 100.dp.toPx() }
    
    Box(
        modifier = modifier
            .pointerInput(currentRoute, enableSwipeToGoBack, swipeThreshold) {
                var totalDrag = 0f
                detectHorizontalDragGestures(
                    onDragStart = {
                        totalDrag = 0f
                    },
                    onHorizontalDrag = { change, dragAmount ->
                        totalDrag += dragAmount
                        // If this is a back swipe and enabled, consume during drag to prevent NavHost from handling it
                        if (totalDrag < -swipeThreshold && enableSwipeToGoBack) {
                            change.consume()
                        }
                    },
                    onDragEnd = {
                        val isBackSwipe = totalDrag < -swipeThreshold
                        if (isBackSwipe && enableSwipeToGoBack && navController.previousBackStackEntry != null) {
                            navController.popBackStack()
                        }
                        totalDrag = 0f
                    },
                    onDragCancel = {
                        totalDrag = 0f
                    }
                )
            }
    ) {
        // Use standard NavHost internally for navigation functionality
        NavHost(
            navController = navController,
            startDestination = startDestination,
            modifier = Modifier,
            enterTransition = enterTransition ?: {
                fadeIn(animationSpec = tween(500))
            },
            exitTransition = exitTransition ?: {
                fadeOut(animationSpec = tween(500))
            },
            popEnterTransition = popEnterTransition ?: {
                fadeIn(animationSpec = tween(500))
            },
            popExitTransition = popExitTransition ?: {
                fadeOut(animationSpec = tween(500))
            },
        ) {
            builder(routeSwipePreferences)
        }
    }
}

/**
 * Extension function to register a composable route with optional swipe-to-go-back control.
 * This should be called from within the CustomNavHost builder lambda.
 * 
 * @param route The route for this destination
 * @param enableSwipeToGoBack Whether swipe-to-go-back gestures should trigger navigation (default: false)
 * @param routeSwipePreferences The shared preferences map (provided by CustomNavHost builder)
 * @param content The composable content for this destination
 */
fun NavGraphBuilder.customComposable(
    route: String,
    enableSwipeToGoBack: Boolean = false,
    routeSwipePreferences: MutableMap<String, Boolean>,
    content: @Composable AnimatedContentScope.(NavBackStackEntry) -> Unit
) {
    // Register the route preference
    routeSwipePreferences[route] = enableSwipeToGoBack
    
    // Use standard composable for actual navigation registration
    composable(route = route, content = content)
}

