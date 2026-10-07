#version 440

layout(location = 0) in vec4 qt_Vertex;
layout(location = 1) in vec2 qt_MultiTexCoord0;
layout(location = 0) out vec2 qt_TexCoord0;

// Keep this block byte-for-byte identical to r50_wpe_surface.frag. Qt Quick
// shares binding 0 between both stages on every RHI backend.
layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    vec2 viewportSize;
    float sceneTime;
    float waterRippleSpeed;
    float waterRippleStrength;
    float surfaceEnabled;
} ubuf;

void main()
{
    qt_TexCoord0 = qt_MultiTexCoord0;
    gl_Position = ubuf.qt_Matrix * qt_Vertex;
}
