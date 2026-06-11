#!/usr/bin/env python3
"""一个会旋转的甜甜圈 (3D ASCII donut) — 向 donut.c 致敬"""

import math
import os
import sys
import time

def render(width=80, height=24, frames=100, delay=0.03):
    """Render a spinning 3D donut in the terminal"""
    
    # Precompute trig values
    theta_spacing = 0.07
    phi_spacing = 0.02
    
    screen = [' '] * width * height
    z_buffer = [0.0] * width * height
    
    A = 1.0  # rotation angle around x-axis
    B = 1.0  # rotation angle around z-axis
    
    for frame in range(frames):
        # Clear buffers
        for i in range(width * height):
            screen[i] = ' '
            z_buffer[i] = 0.0
        
        # θ goes around the cross-section of the torus
        theta = 0.0
        while theta < 2 * math.pi:
            # φ goes around the center of the torus
            phi = 0.0
            while phi < 2 * math.pi:
                # 3D position of the point on the torus before rotation
                # R1 = inner radius, R2 = outer radius
                
                # Precompute sines and cosines for theta
                sin_theta = math.sin(theta)
                cos_theta = math.cos(theta)
                
                # Precompute sines and cosines for phi
                sin_phi = math.sin(phi)
                cos_phi = math.cos(phi)
                
                # Position on the torus surface
                circle_x = 2.0 + cos_theta  # R2 + R1*cos(theta)
                circle_y = sin_theta         # R1*sin(theta)
                
                # 3D coordinates after rotation
                # First rotate around x-axis by A, then around z-axis by B
                x = circle_x * (math.cos(B) * math.cos(phi) + math.sin(A) * math.sin(B) * sin_phi) - circle_y * math.cos(A) * math.sin(B)
                y = circle_x * (math.sin(B) * math.cos(phi) - math.sin(A) * math.cos(B) * sin_phi) + circle_y * math.cos(A) * math.cos(B)
                z = math.cos(A) * circle_x * sin_phi + circle_y * math.sin(A) + 5.0  # +5 for distance from camera
                
                # Project 3D to 2D
                ooz = 1.0 / z  # one over z (perspective)
                xp = int(width / 2 + 30 * ooz * x)
                yp = int(height / 2 - 15 * ooz * y)
                
                # Calculate luminance
                luminance = sin_phi * sin_theta * math.cos(B) - cos_phi * cos_theta * math.sin(A) - sin_phi * cos_theta * math.cos(A) * math.sin(B) + cos_phi * sin_theta * math.sin(A) * math.sin(B) + cos_theta * math.cos(A) * math.sin(B)
                
                if ooz > z_buffer[yp * width + xp] and 0 < xp < width and 0 < yp < height:
                    z_buffer[yp * width + xp] = ooz
                    # Choose ASCII character based on luminance
                    luminance_index = int(8 * luminance)
                    screen[yp * width + xp] = '.,-~:;=!*#$@'[max(0, min(11, luminance_index))]
                
                phi += phi_spacing
            theta += theta_spacing
        
        # Clear screen and render
        sys.stdout.write('\033[H')  # Move cursor to home position
        box = '+'
        for y in range(height):
            row = ''.join(screen[y * width:(y + 1) * width])
            box += row + '|\n|'
        
        # Remove last '|' and add bottom border
        box = box.rstrip('|\n|')
        
        print('┌' + '─' * width + '┐')
        for y in range(height):
            print('│' + ''.join(screen[y * width:(y + 1) * width]) + '│')
        print('└' + '─' * width + '┘')
        
        A += 0.04
        B += 0.02
        
        time.sleep(delay)
    
    # Clean up cursor position
    print(f'\033[{height + 3}B')  # Move down past the donut

if __name__ == '__main__':
    try:
        render(width=60, height=22, frames=150, delay=0.03)
    except KeyboardInterrupt:
        print('\n再见！')
        sys.exit(0)
