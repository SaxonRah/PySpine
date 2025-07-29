/*
// How to use:
    SDL3SpineLoader loader(renderer);
    loader.load_attachment_config("sprite_attachment_config.json");
    loader.load_animation("bone_animation.json");
    loader.play();

// In your game loop:
    loader.update(deltaTime);
    loader.render(centerX, centerY);
*/

#include <SDL3/SDL.h>
#include <nlohmann/json.hpp>
#include <unordered_map>
#include <string>
#include <vector>
#include <fstream>
#include <cmath>
#include <iostream>
#include <memory>

using json = nlohmann::json;

// Enums matching the pygame version
enum class AttachmentPoint {
    START,
    END
};

enum class BoneLayer {
    BEHIND,
    MIDDLE,
    FRONT
};

enum class InterpolationType {
    LINEAR,
    EASE_IN,
    EASE_OUT,
    EASE_IN_OUT,
    BEZIER
};

// Forward declarations
class SDL3SpineLoader;

// Transform structure for animation keyframes
struct PySpineTransform {
    float x = 0.0f;
    float y = 0.0f;
    float rotation = 0.0f;
    float scale = 1.0f;

    PySpineTransform() = default;
    PySpineTransform(const json& data) {
        if (data.contains("x")) x = data["x"];
        if (data.contains("y")) y = data["y"];
        if (data.contains("rotation")) rotation = data["rotation"];
        if (data.contains("scale")) scale = data["scale"];
    }
};

// Sprite class equivalent
class PySpineSprite {
public:
    std::string name;
    int x, y, width, height;
    float origin_x = 0.5f;
    float origin_y = 0.5f;
    SDL_Texture* texture = nullptr;

    PySpineSprite(const json& data) {
        name = data["name"];
        x = data["x"];
        y = data["y"];
        width = data["width"];
        height = data["height"];
        if (data.contains("origin_x")) origin_x = data["origin_x"];
        if (data.contains("origin_y")) origin_y = data["origin_y"];
    }

    ~PySpineSprite() {
        if (texture) {
            SDL_DestroyTexture(texture);
        }
    }
};

// Bone class equivalent
class PySpineBone {
public:
    std::string name;
    float x, y, length, angle;
    std::string parent;
    AttachmentPoint parent_attachment_point = AttachmentPoint::END;
    std::vector<std::string> children;
    BoneLayer layer = BoneLayer::MIDDLE;
    int layer_order = 0;

    // Runtime transform
    float world_x, world_y, world_rotation, world_scale = 1.0f;

    PySpineBone(const json& data) {
        name = data["name"];
        x = data["x"];
        y = data["y"];
        length = data["length"];
        angle = data["angle"];

        if (data.contains("parent")) parent = data["parent"];
        if (data.contains("children")) {
            for (const auto& child : data["children"]) {
                children.push_back(child);
            }
        }

        // Initialize world transform
        world_x = x;
        world_y = y;
        world_rotation = angle;
    }
};

// Sprite instance class equivalent
class PySpineSpriteInstance {
public:
    std::string id;
    std::string sprite_name;
    std::string bone_name;
    float offset_x = 0.0f;
    float offset_y = 0.0f;
    float rotation = 0.0f;
    float scale = 1.0f;

    PySpineSpriteInstance(const json& data) {
        id = data["id"];
        sprite_name = data["sprite_name"];
        if (data.contains("bone_name")) bone_name = data["bone_name"];
        if (data.contains("offset_x")) offset_x = data["offset_x"];
        if (data.contains("offset_y")) offset_y = data["offset_y"];
        if (data.contains("rotation")) rotation = data["rotation"];
        if (data.contains("scale")) scale = data["scale"];
    }
};

// Animation keyframe class
class PySpineKeyframe {
public:
    float time;
    PySpineTransform transform;
    InterpolationType interpolation = InterpolationType::LINEAR;

    PySpineKeyframe(const json& data) {
        time = data["time"];
        transform = PySpineTransform(data["transform"]);

        if (data.contains("interpolation")) {
            std::string interp = data["interpolation"];
            if (interp == "ease_in") interpolation = InterpolationType::EASE_IN;
            else if (interp == "ease_out") interpolation = InterpolationType::EASE_OUT;
            else if (interp == "ease_in_out") interpolation = InterpolationType::EASE_IN_OUT;
            else if (interp == "bezier") interpolation = InterpolationType::BEZIER;
        }
    }
};

// Animation track class
class PySpineAnimationTrack {
public:
    std::string bone_name;
    std::vector<PySpineKeyframe> keyframes;

    PySpineAnimationTrack(const std::string& bone, const json& data)
        : bone_name(bone) {
        for (const auto& kf_data : data["keyframes"]) {
            keyframes.emplace_back(kf_data);
        }
    }

    PySpineTransform get_transform_at_time(float time) const {
        if (keyframes.empty()) return PySpineTransform();
        if (keyframes.size() == 1) return keyframes[0].transform;

        // Find surrounding keyframes
        const PySpineKeyframe* kf1 = nullptr;
        const PySpineKeyframe* kf2 = nullptr;

        for (size_t i = 0; i < keyframes.size() - 1; i++) {
            if (time >= keyframes[i].time && time <= keyframes[i + 1].time) {
                kf1 = &keyframes[i];
                kf2 = &keyframes[i + 1];
                break;
            }
        }

        if (!kf1 || !kf2) {
            return keyframes.back().transform;
        }

        // Calculate interpolation factor
        float duration = kf2->time - kf1->time;
        float t = duration > 0 ? (time - kf1->time) / duration : 0.0f;

        // Apply easing function
        switch (kf1->interpolation) {
            case InterpolationType::EASE_IN:
                t = t * t;
                break;
            case InterpolationType::EASE_OUT:
                t = 1 - (1 - t) * (1 - t);
                break;
            case InterpolationType::EASE_IN_OUT:
                t = t < 0.5f ? 2 * t * t : 1 - std::pow(-2 * t + 2, 3) / 2;
                break;
            case InterpolationType::BEZIER:
                t = t * t * (3.0f - 2.0f * t);
                break;
            default: // LINEAR
                break;
        }

        // Linear interpolation with applied easing
        PySpineTransform result;
        result.x = kf1->transform.x + (kf2->transform.x - kf1->transform.x) * t;
        result.y = kf1->transform.y + (kf2->transform.y - kf1->transform.y) * t;
        result.rotation = kf1->transform.rotation + (kf2->transform.rotation - kf1->transform.rotation) * t;
        result.scale = kf1->transform.scale + (kf2->transform.scale - kf1->transform.scale) * t;

        return result;
    }
};

// Main SDL3 PySpine Loader class
class SDL3SpineLoader {
private:
    SDL_Renderer* renderer;
    SDL_Texture* sprite_sheet = nullptr;
    std::string sprite_sheet_path;

    std::unordered_map<std::string, std::unique_ptr<PySpineSprite>> sprites;
    std::unordered_map<std::string, std::unique_ptr<PySpineBone>> bones;
    std::unordered_map<std::string, std::unique_ptr<PySpineSpriteInstance>> sprite_instances;
    std::unordered_map<std::string, std::unique_ptr<PySpineAnimationTrack>> animation_tracks;

    // Animation properties
    float duration = 5.0f;
    int fps = 30;
    float current_time = 0.0f;
    bool playing = false;

    bool extract_sprite_surface(PySpineSprite* sprite) {
        if (!sprite_sheet) {
            std::cout << "Warning: No sprite sheet loaded for sprite " << sprite->name << std::endl;
            return false;
        }

        // Get sprite sheet dimensions
        int sheet_width, sheet_height;
        SDL_GetTextureSize(sprite_sheet, &sheet_width, &sheet_height);

        // Check bounds
        if (sprite->x < 0 || sprite->y < 0 ||
            sprite->x + sprite->width > sheet_width ||
            sprite->y + sprite->height > sheet_height ||
            sprite->width <= 0 || sprite->height <= 0) {
            std::cout << "Warning: Sprite " << sprite->name << " bounds are outside sprite sheet" << std::endl;
            return false;
        }

        // Create texture for this sprite
        sprite->texture = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA8888,
                                          SDL_TEXTUREACCESS_TARGET,
                                          sprite->width, sprite->height);

        if (!sprite->texture) {
            std::cout << "Error creating texture for sprite " << sprite->name << ": " << SDL_GetError() << std::endl;
            return false;
        }

        // Set as render target and copy sprite region
        SDL_SetRenderTarget(renderer, sprite->texture);
        SDL_Rect src_rect = {sprite->x, sprite->y, sprite->width, sprite->height};
        SDL_Rect dst_rect = {0, 0, sprite->width, sprite->height};
        SDL_RenderTexture(renderer, sprite_sheet, &src_rect, &dst_rect);
        SDL_SetRenderTarget(renderer, nullptr);

        std::cout << "Successfully extracted sprite " << sprite->name << ": "
                  << sprite->width << "x" << sprite->height
                  << " at (" << sprite->x << ", " << sprite->y << ")" << std::endl;
        return true;
    }

    void calculate_bone_world_positions() {
        // Similar to pygame version - calculate world positions for all bones
        for (auto& [name, bone] : bones) {
            if (bone->parent.empty()) {
                // Root bone - use local position
                bone->world_x = bone->x;
                bone->world_y = bone->y;
                bone->world_rotation = bone->angle;
            } else {
                // Child bone - transform by parent
                auto parent_it = bones.find(bone->parent);
                if (parent_it != bones.end()) {
                    PySpineBone* parent_bone = parent_it->second.get();

                    // Calculate attachment point on parent
                    float attach_x, attach_y;
                    if (bone->parent_attachment_point == AttachmentPoint::START) {
                        attach_x = parent_bone->world_x;
                        attach_y = parent_bone->world_y;
                    } else {
                        attach_x = parent_bone->world_x + parent_bone->length *
                                  std::cos(parent_bone->world_rotation * M_PI / 180.0f);
                        attach_y = parent_bone->world_y + parent_bone->length *
                                  std::sin(parent_bone->world_rotation * M_PI / 180.0f);
                    }

                    // Apply bone's local transform
                    bone->world_x = attach_x + bone->x;
                    bone->world_y = attach_y + bone->y;
                    bone->world_rotation = parent_bone->world_rotation + bone->angle;
                }
            }
        }
    }

public:
    SDL3SpineLoader(SDL_Renderer* r) : renderer(r) {}

    ~SDL3SpineLoader() {
        if (sprite_sheet) {
            SDL_DestroyTexture(sprite_sheet);
        }
    }

    bool load_sprite_project(const std::string& filename) {
        try {
            std::cout << "Loading sprite project from: " << filename << std::endl;
            std::ifstream file(filename);
            json data;
            file >> data;

            // Load sprite sheet
            if (data.contains("sprite_sheet_path")) {
                sprite_sheet_path = data["sprite_sheet_path"];
                SDL_Surface* surface = SDL_LoadBMP(sprite_sheet_path.c_str());
                if (surface) {
                    sprite_sheet = SDL_CreateTextureFromSurface(renderer, surface);
                    SDL_DestroySurface(surface);
                    std::cout << "Sprite sheet loaded: " << sprite_sheet_path << std::endl;
                } else {
                    std::cout << "Warning: Sprite sheet not found: " << sprite_sheet_path << std::endl;
                }
            }

            // Load sprite definitions
            int successful_sprites = 0;
            if (data.contains("sprites")) {
                for (const auto& [name, sprite_data] : data["sprites"].items()) {
                    auto sprite = std::make_unique<PySpineSprite>(sprite_data);
                    if (extract_sprite_surface(sprite.get())) {
                        successful_sprites++;
                    }
                    sprites[name] = std::move(sprite);
                }
            }

            std::cout << "Loaded " << sprites.size() << " sprite definitions, "
                      << successful_sprites << " extracted successfully" << std::endl;
            return true;

        } catch (const std::exception& e) {
            std::cout << "Error loading sprite project: " << e.what() << std::endl;
            return false;
        }
    }

    bool load_bone_project(const std::string& filename) {
        try {
            std::cout << "Loading bone project from: " << filename << std::endl;
            std::ifstream file(filename);
            json data;
            file >> data;

            if (data.contains("bones")) {
                for (const auto& [name, bone_data] : data["bones"].items()) {
                    bones[name] = std::make_unique<PySpineBone>(bone_data);
                }
            }

            std::cout << "Loaded " << bones.size() << " bones from " << filename << std::endl;
            return true;

        } catch (const std::exception& e) {
            std::cout << "Error loading bone project: " << e.what() << std::endl;
            return false;
        }
    }

    bool load_attachment_config(const std::string& filename) {
        try {
            std::cout << "Loading attachment config from: " << filename << std::endl;
            std::ifstream file(filename);
            json data;
            file >> data;

            // Load sprites if not already loaded
            if (sprites.empty() && data.contains("sprite_sheet_path")) {
                sprite_sheet_path = data["sprite_sheet_path"];
                SDL_Surface* surface = SDL_LoadBMP(sprite_sheet_path.c_str());
                if (surface) {
                    sprite_sheet = SDL_CreateTextureFromSurface(renderer, surface);
                    SDL_DestroySurface(surface);
                }

                int successful_sprites = 0;
                if (data.contains("sprites")) {
                    for (const auto& [name, sprite_data] : data["sprites"].items()) {
                        auto sprite = std::make_unique<PySpineSprite>(sprite_data);
                        if (extract_sprite_surface(sprite.get())) {
                            successful_sprites++;
                        }
                        sprites[name] = std::move(sprite);
                    }
                }
                std::cout << "Loaded " << sprites.size() << " sprite definitions, "
                          << successful_sprites << " extracted successfully" << std::endl;
            }

            // Load bones if not already loaded
            if (bones.empty() && data.contains("bones")) {
                for (const auto& [name, bone_data] : data["bones"].items()) {
                    bones[name] = std::make_unique<PySpineBone>(bone_data);
                }
                std::cout << "Loaded " << bones.size() << " bones" << std::endl;
            }

            // Load sprite instances
            if (data.contains("sprite_instances")) {
                for (const auto& [instance_id, instance_data] : data["sprite_instances"].items()) {
                    sprite_instances[instance_id] = std::make_unique<PySpineSpriteInstance>(instance_data);
                    std::cout << "Loaded sprite instance: " << instance_id << " ("
                              << sprite_instances[instance_id]->sprite_name << " -> "
                              << sprite_instances[instance_id]->bone_name << ")" << std::endl;
                }
            }

            std::cout << "Loaded attachment config: " << sprite_instances.size() << " sprite instances" << std::endl;
            return true;

        } catch (const std::exception& e) {
            std::cout << "Error loading attachment config: " << e.what() << std::endl;
            return false;
        }
    }

    bool load_animation(const std::string& filename) {
        try {
            std::cout << "Loading animation from: " << filename << std::endl;
            std::ifstream file(filename);
            json data;
            file >> data;

            if (data.contains("duration")) duration = data["duration"];
            if (data.contains("fps")) fps = data["fps"];

            // Load animation tracks
            int total_keyframes = 0;
            if (data.contains("animation_tracks")) {
                for (const auto& [bone_name, track_data] : data["animation_tracks"].items()) {
                    animation_tracks[bone_name] = std::make_unique<PySpineAnimationTrack>(bone_name, track_data);
                    total_keyframes += animation_tracks[bone_name]->keyframes.size();
                }
            }

            std::cout << "Loaded animation: " << duration << "s @ " << fps << " fps, "
                      << animation_tracks.size() << " tracks, " << total_keyframes << " keyframes" << std::endl;
            return true;

        } catch (const std::exception& e) {
            std::cout << "Error loading animation: " << e.what() << std::endl;
            return false;
        }
    }

    void update(float dt) {
        if (!playing) return;

        current_time += dt;
        if (current_time > duration) {
            current_time = fmod(current_time, duration);
        }

        // Apply animation transforms to bones
        for (const auto& [bone_name, track] : animation_tracks) {
            auto bone_it = bones.find(bone_name);
            if (bone_it != bones.end()) {
                PySpineTransform transform = track->get_transform_at_time(current_time);
                PySpineBone* bone = bone_it->second.get();

                // Apply animated transform
                bone->x += transform.x;
                bone->y += transform.y;
                bone->angle += transform.rotation;
                bone->world_scale *= transform.scale;
            }
        }

        // Recalculate world positions
        calculate_bone_world_positions();
    }

    void render(int offset_x = 0, int offset_y = 0) {
        // Render sprite instances attached to bones
        for (const auto& [instance_id, instance] : sprite_instances) {
            auto sprite_it = sprites.find(instance->sprite_name);
            auto bone_it = bones.find(instance->bone_name);

            if (sprite_it != sprites.end() && bone_it != bones.end()) {
                PySpineSprite* sprite = sprite_it->second.get();
                PySpineBone* bone = bone_it->second.get();

                if (sprite->texture) {
                    // Calculate sprite position based on bone transform
                    float sprite_x = bone->world_x + instance->offset_x + offset_x;
                    float sprite_y = bone->world_y + instance->offset_y + offset_y;

                    // Apply origin offset
                    sprite_x -= sprite->width * sprite->origin_x;
                    sprite_y -= sprite->height * sprite->origin_y;

                    SDL_FRect dst_rect = {
                        sprite_x, sprite_y,
                        (float)sprite->width * instance->scale * bone->world_scale,
                        (float)sprite->height * instance->scale * bone->world_scale
                    };

                    // Calculate rotation
                    float rotation = bone->world_rotation + instance->rotation;

                    SDL_RenderTextureRotated(renderer, sprite->texture, nullptr, &dst_rect,
                                           rotation, nullptr, SDL_FLIP_NONE);
                }
            }
        }
    }

    void render_skeleton(int offset_x = 0, int offset_y = 0, SDL_Color color = {255, 255, 255, 128}) {
        SDL_SetRenderDrawColor(renderer, color.r, color.g, color.b, color.a);

        for (const auto& [name, bone] : bones) {
            float start_x = bone->world_x + offset_x;
            float start_y = bone->world_y + offset_y;
            float end_x = start_x + bone->length * std::cos(bone->world_rotation * M_PI / 180.0f);
            float end_y = start_y + bone->length * std::sin(bone->world_rotation * M_PI / 180.0f);

            SDL_RenderLine(renderer, start_x, start_y, end_x, end_y);

            // Draw bone endpoints
            SDL_FRect start_rect = {start_x - 2, start_y - 2, 4, 4};
            SDL_FRect end_rect = {end_x - 2, end_y - 2, 4, 4};
            SDL_RenderFillRect(renderer, &start_rect);
            SDL_RenderFillRect(renderer, &end_rect);
        }
    }

    // Playback controls
    void play() { playing = true; }
    void pause() { playing = false; }
    void stop() { playing = false; current_time = 0.0f; }
    void set_time(float time) { current_time = std::max(0.0f, std::min(duration, time)); }

    // Getters
    float get_current_time() const { return current_time; }
    float get_duration() const { return duration; }
    bool is_playing() const { return playing; }
};

// Example usage function
void example_usage() {
    // Initialize SDL3
    if (!SDL_Init(SDL_INIT_VIDEO)) {
        std::cerr << "SDL Init failed: " << SDL_GetError() << std::endl;
        return;
    }

    SDL_Window* window = SDL_CreateWindow("SDL3 PySpine Loader", 800, 600, 0);
    SDL_Renderer* renderer = SDL_CreateRenderer(window, nullptr);

    // Create loader
    SDL3SpineLoader loader(renderer);

    // Load PySpine data
    if (std::filesystem::exists("sprite_attachment_config.json")) {
        loader.load_attachment_config("sprite_attachment_config.json");
    } else {
        loader.load_sprite_project("sprite_project.json");
        loader.load_bone_project("bone_project.json");
    }

    if (std::filesystem::exists("bone_animation.json")) {
        loader.load_animation("bone_animation.json");
    }

    loader.play();

    // Main loop
    bool running = true;
    bool show_skeleton = false;
    Uint64 last_time = SDL_GetTicks();

    while (running) {
        Uint64 current_time = SDL_GetTicks();
        float dt = (current_time - last_time) / 1000.0f;
        last_time = current_time;

        SDL_Event event;
        while (SDL_PollEvent(&event)) {
            if (event.type == SDL_EVENT_QUIT) {
                running = false;
            } else if (event.type == SDL_EVENT_KEY_DOWN) {
                switch (event.key.key) {
                    case SDLK_SPACE:
                        if (loader.is_playing()) loader.pause();
                        else loader.play();
                        break;
                    case SDLK_R:
                        loader.stop();
                        break;
                    case SDLK_S:
                        show_skeleton = !show_skeleton;
                        break;
                }
            }
        }

        // Update animation
        loader.update(dt);

        // Clear screen
        SDL_SetRenderDrawColor(renderer, 64, 64, 64, 255);
        SDL_RenderClear(renderer);

        // Render character (centered on screen)
        loader.render(400, 300);

        if (show_skeleton) {
            loader.render_skeleton(400, 300, {0, 255, 0, 128});
        }

        SDL_RenderPresent(renderer);
        SDL_Delay(16); // ~60 FPS
    }

    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(window);
    SDL_Quit();
}